"""Base class for network-based metadata providers.

Consolidates the shared HTTP fetch logic with retry, backoff, circuit breaker,
and rate limiting that was previously duplicated across TVMaze, Wikipedia,
and Wikidata providers.
"""

import json
import logging
import time
import urllib.request
from typing import Optional

from ..cache import DiskCache
from ..ratelimit import TokenBucket, CircuitBreaker, full_jitter_backoff
from .base import MetadataProvider

_DEFAULT_HEADERS = {
    "User-Agent": "tvrenamer/0.1 (+https://github.com/eidleweise/Eids-TV-Renamer)",
    "Accept": "application/json",
}


class BaseNetworkProvider(MetadataProvider):
    """Base class providing shared HTTP fetch with retry/backoff/circuit-breaker.

    Subclasses should set:
      - self.name: str (provider name for logging/cache)
      - self.max_retries: int (default 3)
      - self.backoff_base: float (default 0.2)
      - self.backoff_cap: float (default 2.0)
    """

    def __init__(
        self,
        cache: DiskCache,
        name: str,
        limiter: Optional[TokenBucket] = None,
        circuit: Optional[CircuitBreaker] = None,
        headers: Optional[dict] = None,
        max_retries: int = 3,
        backoff_base: float = 0.2,
        backoff_cap: float = 2.0,
    ):
        self.cache = cache
        self.name = name
        self.limiter = limiter or TokenBucket(rate=2, capacity=4)
        self.circuit = circuit or CircuitBreaker(failure_threshold=5, recovery_time=60)
        self.headers = headers or dict(_DEFAULT_HEADERS)
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.backoff_cap = backoff_cap
        self.logger = logging.getLogger(f"providers.{name}")

    def _fetch_json(self, url: str) -> Optional[dict]:
        """Fetch JSON from a URL with rate limiting, retries, and circuit breaking.

        Returns parsed JSON dict on success, or None on failure.
        """
        if self.circuit.is_open():
            return None

        if not self.limiter.wait():
            self.circuit.record_failure()
            return None

        for attempt in range(self.max_retries):
            try:
                req = urllib.request.Request(url, headers=self.headers)
                with urllib.request.urlopen(req, timeout=10) as resp:
                    status = getattr(resp, "status", None) or resp.getcode()
                    if status == 200:
                        data = resp.read()
                        self.circuit.record_success()
                        self.logger.info(
                            "Provider fetch success",
                            extra={"provider": self.name, "url": url},
                        )
                        return json.loads(data.decode("utf-8"))
                    if status == 429:
                        ra = resp.getheader("Retry-After")
                        if ra:
                            try:
                                time.sleep(int(ra))
                            except Exception:
                                time.sleep(1)
                            continue
                    if 500 <= status < 600:
                        raise RuntimeError(f"Server error {status}")
                    return None
            except Exception as ex:
                self.logger.warning(
                    "Provider fetch error",
                    extra={"provider": self.name, "url": url, "error": str(ex)},
                )
                if attempt == self.max_retries - 1:
                    self.circuit.record_failure()
                    return None
                delay = full_jitter_backoff(
                    attempt, base=self.backoff_base, cap=self.backoff_cap
                )
                time.sleep(delay)

        return None
