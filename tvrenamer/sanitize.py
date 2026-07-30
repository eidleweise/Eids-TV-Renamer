import os
import re
import unicodedata
import hashlib

# Windows reserved names (case-insensitive)
_WINDOWS_RESERVED = {
    "CON",
    "PRN",
    "AUX",
    "NUL",
    *(f"COM{i}" for i in range(1, 10)),
    *(f"LPT{i}" for i in range(1, 10)),
}

_ILLEGAL_CHARS = r"<>:\"/\\|?*"
_CONTROL_CHARS_RE = re.compile(r"[\x00-\x1f]")
# collapse dots/underscores/spaces but preserve hyphen/dash as a meaningful separator
_MULTI_SEP_RE = re.compile(r"[._\s]+")


def normalize_unicode(s: str) -> str:
    """Normalize text to Unicode NFC form."""
    return unicodedata.normalize("NFC", s)


def _strip_control_and_illegal(s: str, strict_windows: bool) -> str:
    # Remove C0 control chars
    s = _CONTROL_CHARS_RE.sub("", s)
    # Replace illegal characters with a single space
    s = re.sub(r"[" + re.escape(_ILLEGAL_CHARS) + r"]+", " ", s)
    # Collapse multiple separators into single space
    s = _MULTI_SEP_RE.sub(" ", s)
    s = s.strip()
    # Windows-specific trimming: names cannot end with a dot or space
    if strict_windows:
        s = s.rstrip(". ")
    return s


def _avoid_windows_reserved(name: str) -> str:
    up = name.upper()
    if up in _WINDOWS_RESERVED:
        # Append deterministic short hash to avoid reserved exact match
        h = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
        return f"{name}-{h}"
    return name


def _shorten(name: str, max_len: int) -> str:
    if len(name) <= max_len:
        return name
    # Reserve 9 chars for '-' + 8 hex of hash
    h = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
    keep = max_len - 9
    if keep <= 0:
        # fallback to only hash
        return h
    return name[:keep].rstrip() + "-" + h


def sanitize_filename(
    filename: str,
    max_component: int = 255,
    strict_windows: bool = False,
    space_replacement: str | None = None,
) -> str:
    """Sanitize a single filename (base + extension) for cross-platform safe usage.

    - normalizes unicode to NFC
    - removes control and illegal characters
    - collapses separators
    - avoids Windows reserved names when strict_windows=True
    - shortens the base name to fit max_component
    """
    filename = normalize_unicode(filename)
    base, ext = os.path.splitext(filename)
    base = _strip_control_and_illegal(base, strict_windows)
    if strict_windows:
        base = _avoid_windows_reserved(base)
    # enforce max component length (applies to base, ext excluded)
    max_base = max_component - len(ext)
    if max_base < 1:
        # defensive: ensure at least 1 char
        max_base = 1
    base = _shorten(base, max_base)
    # Final cleanup: collapse spaces into single space
    base = re.sub(r"\s+", " ", base).strip()
    # optionally replace spaces with underscores if requested
    if space_replacement == "underscore":
        base = base.replace(" ", "_")
    return base + ext


def shorten_path(
    path: str,
    max_component: int = 255,
    strict_windows: bool = False,
    space_replacement: str | None = None,
) -> str:
    """Shorten only the final path component (filename) to fit max_component.

    Returns the path with the basename shortened if necessary.
    """
    dirname, filename = os.path.split(path)
    san = sanitize_filename(
        filename,
        max_component=max_component,
        strict_windows=strict_windows,
        space_replacement=space_replacement,
    )
    return os.path.join(dirname, san)


def sanitize_full_path(
    path: str,
    max_path_len: int = 260,
    strict_windows: bool = False,
    space_replacement: str | None = None,
) -> str:
    """Sanitize all path components and ensure the full path length does not exceed max_path_len.

    Strategy:
    - Normalize and sanitize each component separately.
    - If the resulting full path exceeds max_path_len, iteratively shorten the deepest components
      (basename first, then parents) using a deterministic hash suffix until the path fits.
    - On Windows, reserved names are avoided when strict_windows=True.

    This function is deterministic and attempts to preserve as much human-readable text as possible.
    """
    if not path:
        return path

    # Normalize separators and split
    norm = os.path.normpath(path)

    # On Windows, keep drive/UNC prefix separate
    drive = ""
    if os.name == "nt":
        drive, tail = os.path.splitdrive(norm)
        if tail.startswith("\\\\"):
            # UNC path; leave initial backslashes
            pass
        comp_iter = [c for c in tail.split(os.sep) if c]
    else:
        comp_iter = [c for c in norm.split(os.sep) if c]

    # Sanitize each component
    sanitized = []
    for comp in comp_iter:
        # Keep extensions for final component
        if comp == comp_iter[-1]:
            # apply space replacement only to final filename component
            san = sanitize_filename(
                comp,
                max_component=255,
                strict_windows=strict_windows,
                space_replacement=space_replacement,
            )
        else:
            # directory names: only normalize unicode and remove truly illegal chars
            # Do NOT collapse underscores or dots into spaces (preserve original dir names)
            san = normalize_unicode(comp)
            san = _CONTROL_CHARS_RE.sub("", san)
            san = re.sub(r"[" + re.escape(_ILLEGAL_CHARS) + r"]+", " ", san)
            san = san.strip()
            if strict_windows:
                san = san.rstrip(". ")
                san = _avoid_windows_reserved(san)
        sanitized.append(san)

    # Rebuild and measure
    def build_path(comps):
        path_body = os.sep.join(comps)
        full = (
            (drive + path_body)
            if drive
            else (os.sep + path_body if path.startswith(os.sep) else path_body)
        )
        return full

    full = build_path(sanitized)
    if len(full) <= max_path_len:
        return full

    # Need to shorten components. Work from deepest component upwards.

    # Helper to shorten a component deterministically
    def shorten_component(name: str, reduce_by: int) -> str:
        target = max(1, len(name) - reduce_by)
        return _shorten(name, target)

    # Iteratively reduce components, prioritizing the basename
    i = len(sanitized) - 1
    max_iterations = len(sanitized) * 3  # Safety cap: at most 3 passes over all components
    iterations = 0
    while len(build_path(sanitized)) > max_path_len and i >= 0:
        iterations += 1
        if iterations > max_iterations:
            break  # Prevent infinite loop on pathological inputs
        comp = sanitized[i]
        need = len(build_path(sanitized)) - max_path_len
        # limit reduction to avoid removing extension dot+ext for final file
        if i == len(sanitized) - 1:
            base, ext = os.path.splitext(comp)
            # compute target length for the base (preserve extension)
            target_base_len = max(1, len(base) - need)
            new_base = _shorten(base, target_base_len)
            new_comp = new_base + ext
        else:
            max_comp_len = max(1, len(comp) - need)
            new_comp = _shorten(comp, max_comp_len)
        sanitized[i] = new_comp
        i -= 1
        if i < 0:
            # wrap around to keep trimming from the end again
            i = len(sanitized) - 1
            # If we've looped multiple times and cannot make progress, break to avoid infinite loop
            # (fallback: produce a path with hashed basename)
            if len(build_path(sanitized)) > max_path_len:
                # Forcefully shorten basename to minimal + hash (preserve extension)
                basename = sanitized[-1]
                b_base, b_ext = os.path.splitext(basename)
                san_min = _shorten(b_base, 8) + b_ext
                sanitized[-1] = san_min
                break

    final = build_path(sanitized)
    # As a last resort, if still too long, return a hashed filename path in the same directory
    if len(final) > max_path_len:
        # hash the full original path and create short filename
        h = hashlib.sha1(path.encode("utf-8")).hexdigest()[:12]
        dirname = os.sep.join(sanitized[:-1])
        ext = os.path.splitext(sanitized[-1])[1]
        final_basename = f"file-{h}{ext}"
        final = (
            (drive + os.sep + dirname + os.sep + final_basename)
            if drive
            else (os.sep.join([dirname, final_basename]) if dirname else final_basename)
        )
    return final
