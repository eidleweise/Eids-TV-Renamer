"""Shared utility functions for tvrenamer."""

import json
import os
import tempfile


def atomic_write_json(path: str, data: dict, indent: int = None, ensure_ascii: bool = False):
    """Write JSON data to a file atomically (write-to-temp + rename).

    Ensures readers never see a partially written file. Uses fsync for durability.

    Args:
        path: Destination file path.
        data: Dict to serialize as JSON.
        indent: JSON indentation (None for compact, 2 for readable).
        ensure_ascii: If True, escape non-ASCII characters.
    """
    dirn = os.path.dirname(path) or "."
    os.makedirs(dirn, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix="._atomic_", dir=dirn)
    try:
        try:
            f = os.fdopen(fd, "w")
        except Exception:
            os.close(fd)
            raise
        with f:
            json.dump(data, f, indent=indent, ensure_ascii=ensure_ascii)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            try:
                os.unlink(tmp)
            except Exception:
                pass
