import os
import json
import shutil
import tempfile
import hashlib
import time
import uuid
from dataclasses import dataclass, asdict
from typing import List, Optional
import logging

JOURNAL_VERSION = 1


@dataclass
class Operation:
    id: str
    src: str
    dst: str
    temp: Optional[str] = None
    checksum: Optional[str] = None
    state: str = "pending"  # pending | done | rolledback | failed


@dataclass
class Journal:
    version: int
    journal_id: str
    timestamp: float
    operations: List[Operation]
    state: str = "pending"  # pending | committed | rolled_back
    run_id: Optional[str] = None


logger = logging.getLogger("renamer.transaction")


def _atomic_write_json(path: str, data: dict):
    from ..utils import atomic_write_json
    atomic_write_json(path, data, indent=2)
    # Log the write with journal correlation info
    try:
        jid = data.get("journal_id") or data.get("journal", {}).get("journal_id")
    except Exception:
        jid = None
    run_id = (
        data.get("run_id") or data.get("journal", {}).get("run_id")
        if isinstance(data, dict)
        else None
    )
    extra = {"event": "journal_write", "path": path}
    if jid:
        extra["journal_id"] = jid
    if run_id:
        extra["run_id"] = run_id
    logger.info("Wrote journal", extra=extra)


def build_transaction(plan: List[tuple], run_id: Optional[str] = None) -> Journal:
    ops = []
    for src, dst in plan:
        ops.append(
            Operation(
                id=str(uuid.uuid4()), src=os.path.abspath(src), dst=os.path.abspath(dst)
            )
        )
    j = Journal(
        version=JOURNAL_VERSION,
        journal_id=str(uuid.uuid4()),
        timestamp=time.time(),
        operations=ops,
        run_id=run_id,
    )
    return j


def write_journal_atomically(journal: Journal, path: str) -> str:
    # path is the target directory for the journal file
    path = os.path.abspath(path)
    os.makedirs(path, exist_ok=True)
    data = asdict(journal)
    dest = os.path.join(path, f"transaction_{journal.journal_id}.json")
    _atomic_write_json(dest, data)
    return dest


def _read_journal(path: str) -> Journal:
    with open(path, "r") as f:
        data = json.load(f)
    ops = [Operation(**op) for op in data["operations"]]
    j = Journal(
        version=data.get("version", 1),
        journal_id=data.get("journal_id", ""),
        timestamp=data.get("timestamp", 0.0),
        operations=ops,
        state=data.get("state", "pending"),
        run_id=data.get("run_id"),
    )
    return j


def _write_journal_state(path: str, journal: Journal):
    data = asdict(journal)
    _atomic_write_json(path, data)


def preflight_checks(journal: Journal) -> None:
    # ensure src exists and dst parents writable
    for op in journal.operations:
        if not os.path.exists(op.src):
            raise FileNotFoundError(f"Source not found: {op.src}")
        dst_parent = os.path.dirname(op.dst) or "."
        if not os.path.isdir(dst_parent):
            # attempt to create target directory
            os.makedirs(dst_parent, exist_ok=True)
        # permission check
        if not os.access(dst_parent, os.W_OK):
            raise PermissionError(
                f"No write permission to destination directory: {dst_parent}"
            )


def _same_fs(path1: str, path2: str) -> bool:
    try:
        return os.stat(path1).st_dev == os.stat(os.path.dirname(path2) or ".").st_dev
    except Exception:
        return False


def _compute_checksum(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(8192)
            if not chunk:
                break
            h.update(chunk)
    return h.hexdigest()


def execute_transaction(
    journal_path: str, simulate_fail_after: Optional[int] = None
) -> None:
    """Execute a journaled transaction.

    If simulate_fail_after is set, raise an exception after that many successful
    operations (used for testing rollback behavior).
    """
    journal = _read_journal(journal_path)
    if journal.state != "pending":
        raise RuntimeError("Journal not in pending state")

    logger.info(
        "Starting transaction execution",
        extra={"journal_id": journal.journal_id, "event": "transaction_start"},
    )
    preflight_checks(journal)

    # execute operations in order
    for idx, op in enumerate(journal.operations):
        try:
            # if already done (resuming), skip
            if op.state == "done":
                logger.debug(
                    "Skipping already-done op",
                    extra={"journal_id": journal.journal_id, "op_id": op.id},
                )
                continue

            dst_parent = os.path.dirname(op.dst) or "."
            os.makedirs(dst_parent, exist_ok=True)

            # Pre-check: advisory guard against destination collision.
            # Note: There's an inherent TOCTOU window between this check and the
            # actual move. For same-filesystem moves, we use os.link() which will
            # raise FileExistsError atomically if dst exists. For cross-fs, we rely
            # on the advisory check since copy+replace has no atomic alternative.
            if os.path.exists(op.dst):
                raise FileExistsError(f"Destination exists: {op.dst}")

            if _same_fs(op.src, op.dst):
                # Use link+unlink for atomic move that fails if dst exists
                try:
                    os.link(op.src, op.dst)
                    os.unlink(op.src)
                except OSError:
                    # Fallback for filesystems that don't support hard links
                    os.replace(op.src, op.dst)
            else:
                # cross-fs: copy to temp in dest, then link exclusively to dst, then unlink src.
                # Use O_CREAT|O_EXCL to atomically fail if dst appeared between check and create.
                fd, tmp = tempfile.mkstemp(prefix=".staging_", dir=dst_parent)
                os.close(fd)
                shutil.copy2(op.src, tmp)
                try:
                    # Attempt exclusive creation at destination
                    excl_fd = os.open(op.dst, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                    os.close(excl_fd)
                    # Exclusive create succeeded — now replace the empty file with our staged copy
                    os.replace(tmp, op.dst)
                except FileExistsError:
                    # Destination appeared between our check and now — clean up and fail
                    os.unlink(tmp)
                    raise FileExistsError(f"Destination appeared during cross-fs move: {op.dst}")
                except OSError:
                    # O_EXCL not supported — fall back to replace (best effort)
                    os.replace(tmp, op.dst)
                try:
                    os.unlink(op.src)
                except Exception:
                    # if we can't remove source, mark but continue
                    pass
                op.temp = tmp

            # compute checksum of dst for verification
            try:
                op.checksum = _compute_checksum(op.dst)
            except Exception:
                op.checksum = None

            op.state = "done"
            _write_journal_state(journal_path, journal)
            logger.info(
                "Operation applied",
                extra={
                    "journal_id": journal.journal_id,
                    "op_id": op.id,
                    "src": op.src,
                    "dst": op.dst,
                },
            )

            # simulate failure for testing
            if simulate_fail_after is not None and idx + 1 >= simulate_fail_after:
                raise RuntimeError("Simulated failure during transaction")

        except Exception as e:
            # if this op had completed, keep it marked done so rollback can find it; otherwise mark failed
            if op.state != "done":
                op.state = "failed"
            _write_journal_state(journal_path, journal)
            logger.error(
                "Operation failed, initiating rollback",
                extra={
                    "journal_id": journal.journal_id,
                    "op_id": op.id,
                    "error": str(e),
                },
            )
            # perform rollback of completed ops
            rollback_transaction(journal_path)
            raise

    journal.state = "committed"
    _write_journal_state(journal_path, journal)
    logger.info(
        "Transaction committed",
        extra={"journal_id": journal.journal_id, "event": "transaction_committed"},
    )


def rollback_transaction(journal_path: str) -> None:
    journal = _read_journal(journal_path)
    # iterate in reverse, move any 'done' dst back to src
    rollback_failures = 0
    for op in reversed(journal.operations):
        try:
            if op.state != "done":
                continue
            # If dst exists and src does not, move back
            if os.path.exists(op.dst) and not os.path.exists(op.src):
                dst_parent = os.path.dirname(op.src) or "."
                os.makedirs(dst_parent, exist_ok=True)
                # try atomic move back if same fs
                if _same_fs(op.dst, op.src):
                    os.replace(op.dst, op.src)
                else:
                    # copy back then remove dst
                    fd, tmp = tempfile.mkstemp(prefix=".staging_rb_", dir=dst_parent)
                    os.close(fd)
                    shutil.copy2(op.dst, tmp)
                    os.replace(tmp, op.src)
                    try:
                        os.unlink(op.dst)
                    except Exception:
                        pass
                op.state = "rolledback"
                _write_journal_state(journal_path, journal)
            elif os.path.exists(op.dst) and os.path.exists(op.src):
                # Both exist — can't rollback safely, mark as failed
                op.state = "rollback_failed"
                rollback_failures += 1
                logger.error(
                    "Rollback failed: both source and destination exist",
                    extra={"op_id": op.id, "src": op.src, "dst": op.dst},
                )
                _write_journal_state(journal_path, journal)
        except Exception as e:
            # Mark the operation as failed rather than silently skipping
            op.state = "rollback_failed"
            rollback_failures += 1
            logger.error(
                "Rollback failed for operation",
                extra={"op_id": op.id, "error": str(e)},
            )
            _write_journal_state(journal_path, journal)
            continue

    # Only mark as fully rolled_back if all operations succeeded
    if rollback_failures > 0:
        journal.state = "partially_rolled_back"
        logger.warning(
            "Rollback incomplete: %d operation(s) failed", rollback_failures,
        )
    else:
        journal.state = "rolled_back"
    _write_journal_state(journal_path, journal)


# --- History File Support ---


def write_history_file(journal: Journal, target_dir: str) -> Optional[str]:
    """Write a JSON undo history file after a successful commit.

    The history file is named renamed_history_YYYYMMDD_HHMMSS.json and contains:
    - timestamp: ISO 8601 with timezone offset
    - run_id: UUID matching the transaction's correlation identifier
    - renamed_files: array of {original, new} with absolute paths

    Returns the path to the history file, or None if:
    - The journal has no completed rename operations
    - The write fails (logged but does NOT trigger rollback)
    """
    # Only write if there are actual renames
    renamed_files = []
    for op in journal.operations:
        if op.state == "done":
            renamed_files.append({
                "original": op.src,
                "new": op.dst,
            })

    if not renamed_files:
        return None

    # Generate timestamp in ISO 8601 with timezone
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).astimezone()
    timestamp_iso = now.isoformat()
    timestamp_file = now.strftime("%Y%m%d_%H%M%S")

    history_data = {
        "timestamp": timestamp_iso,
        "run_id": journal.run_id or journal.journal_id,
        "renamed_files": renamed_files,
    }

    filename = f"renamed_history_{timestamp_file}.json"
    history_path = os.path.join(target_dir, filename)

    try:
        _atomic_write_json(history_path, history_data)
        logger.info(
            "History file written",
            extra={
                "event": "history_write",
                "path": history_path,
                "run_id": history_data["run_id"],
                "count": len(renamed_files),
            },
        )
        return history_path
    except Exception as e:
        logger.error(
            "Failed to write history file (renames NOT rolled back)",
            extra={
                "event": "history_write_failed",
                "error": str(e),
                "run_id": history_data["run_id"],
            },
        )
        return None


# --- Undo Support ---


def parse_history_file(path: str) -> dict:
    """Parse and validate a JSON history file.

    Returns the parsed dict with 'renamed_files' array.
    Raises InvalidConfigError if file is missing, unreadable, or invalid format.
    """
    from ..exceptions import InvalidConfigError

    if not os.path.exists(path):
        raise InvalidConfigError(f"History file not found: {path}")

    try:
        with open(path, "r") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        raise InvalidConfigError(f"History file format is invalid: {path} ({e})")

    if not isinstance(data, dict):
        raise InvalidConfigError(f"History file format is invalid: {path}")

    renamed_files = data.get("renamed_files")
    if not isinstance(renamed_files, list):
        raise InvalidConfigError(
            f"History file format is invalid: missing 'renamed_files' array in {path}"
        )

    # Validate each entry has 'original' and 'new' string fields
    for i, entry in enumerate(renamed_files):
        if not isinstance(entry, dict):
            raise InvalidConfigError(
                f"History file format is invalid: entry {i} is not an object in {path}"
            )
        if not isinstance(entry.get("original"), str) or not isinstance(entry.get("new"), str):
            raise InvalidConfigError(
                f"History file format is invalid: entry {i} missing 'original'/'new' strings in {path}"
            )

    return data


def build_undo_plan(history_data: dict, allowed_root: Optional[str] = None) -> List[tuple]:
    """Build a reversal plan from a parsed history file.

    Maps each 'new' path back to its 'original' path.
    Skips entries where the 'new' file no longer exists (logs warning).
    Handles conflicts where 'original' path already has a file (counter suffix).

    Security: If allowed_root is provided, both source and destination must be
    within that root directory. Paths outside the root are rejected to prevent
    arbitrary file relocation via crafted history files.

    Returns a list of (current_path, target_path) tuples.
    """
    plan = []
    renamed_files = history_data.get("renamed_files", [])

    # Resolve allowed root for path boundary validation
    if allowed_root:
        abs_root = os.path.realpath(os.path.abspath(allowed_root))
    else:
        abs_root = None

    for entry in renamed_files:
        src = entry["new"]       # current location (was renamed TO here)
        dst = entry["original"]  # restore TO here

        # Path boundary validation: reject paths outside allowed root
        if abs_root:
            real_src = os.path.realpath(os.path.abspath(src))
            real_dst = os.path.realpath(os.path.abspath(dst))
            if not real_src.startswith(abs_root + os.sep) and real_src != abs_root:
                logger.warning(
                    "Undo: source path outside allowed root, skipping",
                    extra={"path": src, "root": abs_root, "event": "undo_path_rejected"},
                )
                continue
            if not real_dst.startswith(abs_root + os.sep) and real_dst != abs_root:
                logger.warning(
                    "Undo: destination path outside allowed root, skipping",
                    extra={"path": dst, "root": abs_root, "event": "undo_path_rejected"},
                )
                continue

        # Check if source still exists
        if not os.path.exists(src):
            logger.warning(
                "Undo: source file no longer exists, skipping",
                extra={"path": src, "event": "undo_skip_missing"},
            )
            continue

        # Check if destination already has a file
        final_dst = dst
        if os.path.exists(dst):
            # Apply counter suffix
            base, ext = os.path.splitext(dst)
            counter = 1
            while os.path.exists(final_dst):
                final_dst = f"{base} ({counter}){ext}"
                counter += 1
            logger.warning(
                "Undo: original path already occupied, using suffix",
                extra={
                    "original": dst,
                    "adjusted": final_dst,
                    "event": "undo_conflict",
                },
            )

        plan.append((src, final_dst))

    return plan
