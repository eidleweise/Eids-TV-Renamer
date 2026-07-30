import os
import json
import time
import hashlib
import tempfile
import threading
from typing import Any, Callable, Optional, Dict
import logging

try:
    import fcntl
    _HAS_FCNTL = True
except ImportError:
    _HAS_FCNTL = False

logger = logging.getLogger("cache")

DEFAULT_TTL = 7 * 24 * 3600  # 7 days

CACHE_VERSION = 1
META_KEY = "_meta"


def _compute_data_checksum(data: dict) -> str:
    """Compute SHA-256 hex digest over the data payload (excluding _meta).

    Serializes with sorted keys for deterministic output.
    """
    # Filter out _meta
    payload = {k: v for k, v in data.items() if k != META_KEY}
    serialized = json.dumps(payload, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(serialized).hexdigest()


class DiskCache:
    def __init__(self, path: str, ttl: int = DEFAULT_TTL, max_items: int = 1000):
        self.path = path
        self.ttl = ttl
        self.max_items = max_items
        self._max_stale_refreshes = 3  # Max background refresh attempts before giving up
        self._persist_interval = 60  # Minimum seconds between background persists
        self._last_persist_time = 0
        dirn = os.path.dirname(self.path)
        if dirn:
            os.makedirs(dirn, exist_ok=True)
        self._lock = threading.Lock()
        # load cache on init
        self._load()

    def _load(self):
        self._data = {}
        if not os.path.exists(self.path):
            return

        # Security: reject symlinks to prevent cache poisoning
        if os.path.islink(self.path):
            logger.warning(
                "Cache file is a symlink — refusing to load (possible poisoning attempt): %s",
                self.path,
            )
            return

        try:
            with open(self.path, "r") as f:
                raw = json.load(f)
        except Exception:
            # Can't even parse JSON — treat as corrupt
            self._rotate_corrupt()
            return

        if not isinstance(raw, dict):
            self._rotate_corrupt()
            return

        # Check version
        meta = raw.get(META_KEY)
        if meta is None or not isinstance(meta, dict):
            # No meta entry — legacy cache, discard data and start fresh
            logger.info("Cache missing _meta entry, starting fresh")
            self._data = {}
            return

        version = meta.get("version")
        if version is None or version < CACHE_VERSION:
            # Outdated version — discard data, start fresh
            logger.info(
                "Cache version %s < %s, discarding cached data",
                version, CACHE_VERSION,
            )
            self._data = {}
            return

        # Validate checksum
        stored_checksum = meta.get("checksum", "")
        # Compute checksum over data (excluding _meta)
        data_without_meta = {k: v for k, v in raw.items() if k != META_KEY}
        computed_checksum = _compute_data_checksum(raw)

        if stored_checksum != computed_checksum:
            logger.warning(
                "Cache checksum mismatch (stored=%s, computed=%s), rotating corrupt file",
                stored_checksum[:16], computed_checksum[:16],
            )
            self._rotate_corrupt()
            return

        # Valid cache — load data (without _meta)
        self._data = data_without_meta

        # Prune on load if cache exceeds max_items (handles externally grown caches)
        if len(self._data) > self.max_items:
            self._prune_if_needed()

    def _rotate_corrupt(self):
        """Rename corrupt cache file to .corrupt.{epoch_seconds} and start fresh."""
        self._data = {}
        if not os.path.exists(self.path):
            return
        epoch = int(time.time())
        corrupt_path = f"{self.path}.corrupt.{epoch}"
        try:
            os.rename(self.path, corrupt_path)
            logger.warning("Rotated corrupt cache to %s", corrupt_path)
        except OSError as e:
            logger.warning(
                "Failed to rotate corrupt cache file: %s", e
            )
            # Proceed with empty in-memory cache

    def _atomic_write(self, data: dict):
        """Atomically write cache data with inter-process file locking."""
        from .utils import atomic_write_json
        lock_path = self.path + ".lock"
        if _HAS_FCNTL:
            try:
                lock_fd = os.open(lock_path, os.O_CREAT | os.O_WRONLY)
                fcntl.flock(lock_fd, fcntl.LOCK_EX)
                try:
                    atomic_write_json(self.path, data)
                finally:
                    fcntl.flock(lock_fd, fcntl.LOCK_UN)
                    os.close(lock_fd)
            except OSError:
                # If locking fails, proceed without lock (best effort)
                atomic_write_json(self.path, data)
        else:
            atomic_write_json(self.path, data)

    def _prune_if_needed(self):
        if len(self._data) <= self.max_items:
            return
        # LRU eviction based on 'atime' field
        items = sorted(self._data.items(), key=lambda kv: kv[1].get("atime", 0))
        while len(items) > self.max_items:
            k, _ = items.pop(0)
            self._data.pop(k, None)

    def _persist(self):
        # called with self._lock held
        self._prune_if_needed()
        try:
            # Strip runtime-only fields (prefixed with _) from entries before persisting.
            # These are internal tracking state (e.g., _refresh_attempts) that shouldn't
            # be stored on disk or affect the checksum.
            clean_data = {}
            for k, v in self._data.items():
                if isinstance(v, dict):
                    clean_data[k] = {fk: fv for fk, fv in v.items() if not fk.startswith("_")}
                else:
                    clean_data[k] = v

            # Build output with _meta entry containing version and checksum
            checksum = _compute_data_checksum(clean_data)
            output = dict(clean_data)
            output[META_KEY] = {
                "version": CACHE_VERSION,
                "checksum": checksum,
            }
            self._atomic_write(output)
        except Exception:
            pass

    def _now(self):
        return int(time.time())

    def _make_key(self, namespace: str, key: str) -> str:
        return namespace + ":" + key

    def get(
        self,
        namespace: str,
        key: str,
        loader: Optional[Callable[[], Any]] = None,
        stale_while_revalidate: bool = True,
        extra: Optional[Dict] = None,
    ) -> Any:
        k = self._make_key(namespace, key)
        with self._lock:
            entry = self._data.get(k)
            if entry:
                now = self._now()
                if now - entry.get("ts", 0) <= self.ttl:
                    entry["atime"] = now
                    # Throttle background persist: only write if enough time has passed
                    if now - self._last_persist_time >= self._persist_interval:
                        self._last_persist_time = now
                        threading.Thread(target=self._persist, daemon=True).start()
                    logger.debug(
                        "Cache hit",
                        extra={"namespace": namespace, "key": key, **(extra or {})},
                    )
                    return entry.get("value")
                else:
                    # expired
                    val = entry.get("value")
                    logger.debug(
                        "Cache expired",
                        extra={"namespace": namespace, "key": key, **(extra or {})},
                    )
                    if loader and stale_while_revalidate:
                        # Check if we've exceeded max stale refresh attempts
                        refresh_attempts = entry.get("_refresh_attempts", 0)
                        if refresh_attempts < self._max_stale_refreshes:
                            threading.Thread(
                                target=self._refresh_bg,
                                args=(namespace, key, loader, extra),
                                daemon=True,
                            ).start()
                        else:
                            logger.debug(
                                "Max stale refresh attempts reached, not retrying",
                                extra={"namespace": namespace, "key": key},
                            )
                        return val
                    # else fall through to loader
            # no entry or expired and no stale
            logger.debug(
                "Cache miss",
                extra={"namespace": namespace, "key": key, **(extra or {})},
            )
        if loader:
            val = loader()
            try:
                self.set(namespace, key, val, extra=extra)
            except Exception:
                pass
            return val
        return None

    def _refresh_bg(
        self,
        namespace: str,
        key: str,
        loader: Callable[[], Any],
        extra: Optional[Dict] = None,
    ):
        try:
            val = loader()
            with self._lock:
                self._data[self._make_key(namespace, key)] = {
                    "value": val,
                    "ts": self._now(),
                    "atime": self._now(),
                }
                self._persist()
            logger.info(
                "Background cache refresh",
                extra={"namespace": namespace, "key": key, **(extra or {})},
            )
        except Exception as ex:
            # Increment refresh attempt counter so stale data isn't served forever
            with self._lock:
                k = self._make_key(namespace, key)
                entry = self._data.get(k)
                if entry:
                    entry["_refresh_attempts"] = entry.get("_refresh_attempts", 0) + 1
            logger.warning(
                "Background cache refresh failed",
                extra={
                    "namespace": namespace,
                    "key": key,
                    "error": str(ex),
                    **(extra or {}),
                },
            )

    def set(self, namespace: str, key: str, value: Any, extra: Optional[Dict] = None):
        with self._lock:
            k = self._make_key(namespace, key)
            self._data[k] = {"value": value, "ts": self._now(), "atime": self._now()}
            self._persist()
        logger.info(
            "Cache set", extra={"namespace": namespace, "key": key, **(extra or {})}
        )

    def invalidate(self, namespace: str, key: str):
        with self._lock:
            k = self._make_key(namespace, key)
            if k in self._data:
                del self._data[k]
                self._persist()

    def clear(self):
        with self._lock:
            self._data = {}
            self._persist()
