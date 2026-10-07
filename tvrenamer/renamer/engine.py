import os
import re
import fnmatch
import logging
from typing import List, Tuple, Optional
from ..sanitize import sanitize_full_path, sanitize_filename
from .transaction import (
    build_transaction,
    write_journal_atomically,
    execute_transaction,
    write_history_file,
    _read_journal,
)
from .. import logging_setup
from ..cache import DiskCache
from ..config import (
    DEFAULT_DIRECTORY_BLACKLIST,
    get_directory_blacklist,
    get_scene_tags,
    get_junk_extensions,
)
from ..providers.tvmaze import TVMazeProvider
from ..providers.wikipedia import WikipediaProvider
from ..providers.wikidata import WikidataProvider
from ..providers.chain import ProviderChain

_PROVIDER_MAP = {
    "tvmaze": TVMazeProvider,
    "wikipedia": WikipediaProvider,
    "wikidata": WikidataProvider,
}


def build_providers_from_config(
    cache: DiskCache,
    config: dict | None = None,
    order_override: List[str] | None = None,
) -> List:
    """Construct provider instances from config dict or order_override.

    config example:
    { 'providers': {'order': ['tvmaze','wikidata']}, 'provider': {'tvmaze': {'enabled': True}} }
    """
    providers = []
    if order_override:
        order = order_override
    else:
        order = []
        if config:
            p = config.get("providers", {})
            order = p.get("order", [])
    if not order:
        order = ["tvmaze", "wikidata", "wikipedia"]
    for name in order:
        cls = _PROVIDER_MAP.get(name.lower())
        if not cls:
            continue
        # provider-specific config may exist under either 'provider' or 'providers' sections
        provider_conf = None
        if config:
            provider_conf = (config.get("provider") or {}).get(name) or (config.get("providers") or {}).get(name)
        headers = None
        if provider_conf and isinstance(provider_conf, dict):
            headers = provider_conf.get("headers")
        # pass headers to provider constructors when supported
        try:
            providers.append(cls(cache, headers=headers) if headers is not None else cls(cache))
        except TypeError:
            # provider doesn't accept headers in constructor — fall back
            providers.append(cls(cache))
    return providers


VIDEO_EXTS = {".mkv", ".mp4", ".avi", ".m4v", ".ts", ".wmv", ".mov"}
SUBTITLE_EXTS = {".srt", ".vtt", ".sub", ".ass", ".idx", ".ssa", ".smi"}

from ..config import DEFAULT_DIRECTORY_BLACKLIST

SHORT_WORDS = {
    "a", "an", "the", "and", "but", "or", "nor", "for", "yet", "so",
    "in", "on", "at", "to", "by", "of", "up", "is",
}

# Season directory pattern: "Season N", "season N", "Season_N", "S01", "s01", "season.N"
_SEASON_DIR_RE = re.compile(
    r"^(?:season[\s._-]*(\d{1,2})|[sS](\d{1,2}))$", re.IGNORECASE
)

# Year pattern: 4-digit number 1950-2099
_YEAR_RE = re.compile(r"\b((?:19[5-9]\d|20\d{2}))\b")

# SxxExx or season/episode marker patterns (used for year extraction positioning)
_SE_MARKER_RE = re.compile(
    r"[sS]\d{1,2}[eE]\d|(?<!\d)\d{1,2}x\d{1,2}", re.IGNORECASE
)

# Standalone season token used only to truncate a show *title* at its season
# boundary (e.g. "My Show S01 ..." → "My Show", "Show Season 08" → "Show").
# The lookarounds enforce a token boundary so a bare "S" or a title like
# "S.W.A.T." (normalized to "S W A T", no attached digits) is NOT matched —
# only an "S" immediately followed by 1-2 digits as a standalone token.
_SE_TRUNCATE_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:[sS]\d{1,2}|season[\s._-]*\d{1,2})(?![A-Za-z0-9])",
    re.IGNORECASE,
)


def _is_season_dir(name: str) -> Optional[int]:
    """Return season number if name matches a season directory pattern, else None.

    Matches: "Season 1", "season 02", "Season_3", "S01", "s01", "season.1"
    """
    m = _SEASON_DIR_RE.match(name.strip())
    if not m:
        return None
    # Group 1 is from "season N" pattern, group 2 is from "S01" pattern
    num_str = m.group(1) or m.group(2)
    if num_str is not None:
        return int(num_str)
    return None


# Pattern for season suffix embedded in a directory name like "A Show Season 08".
# The captured season number is validated against the project's valid-season
# notion (see ``_is_season_dir``) so a trailing season-zero ("S0") or any
# Pattern for a season suffix embedded in a directory name like "A Show
# Season 08" or "Show S01". The season token must be a *standalone* token —
# preceded by a whitespace/separator boundary — so a name without a real
# boundary (e.g. "0S1", where "S1" is glued to a digit) is left untouched.
# The captured season number is validated against the project's valid-season
# notion (see ``_is_season_dir``) so a trailing season-zero ("S0") is NOT
# stripped either.
_SEASON_SUFFIX_RE = re.compile(
    r"^(?P<show>.+?)[\s._-]+(?:season[\s._-]*(?P<snum>\d{1,2})|[sS](?P<snum2>\d{1,2}))$",
    re.IGNORECASE,
)


def _extract_show_from_dir_name(name: str) -> str:
    """Extract show name from a directory that may contain a season suffix.

    Examples:
        "A Show Season 08" → "A Show"
        "Show S01" → "Show"
        "Plain Directory" → "Plain Directory" (unchanged)
        "0S0" → "0S0" (season zero is not a valid season, left unchanged)
        "0S1" → "0S1" (no token boundary before "S1", left unchanged)
    """
    m = _SEASON_SUFFIX_RE.match(name.strip())
    if m:
        num_str = m.group("snum") or m.group("snum2")
        # Only strip the suffix when it is a valid season (season zero is
        # rejected, matching the behaviour of ``_is_season_dir``).
        if num_str is not None and int(num_str) > 0:
            return m.group("show").strip()
    return name


def _resolve_show_name(
    filepath: str,
    root: str,
    config: Optional[dict] = None,
) -> str:
    """Resolve the show name by walking ancestor directories.

    Logic:
    1. If parent is a season dir → use grandparent (if not blacklisted)
    2. Otherwise use parent dir (if not blacklisted)
    3. Walk up to 5 ancestors, skipping blacklisted names
    4. Fall back to filename extraction or "Unknown"
    """
    if config is None:
        config = {}

    user_blacklist = get_directory_blacklist(config)
    # Merge user blacklist with defaults (case-insensitive dedup)
    seen_lower = set()
    merged_blacklist = []
    for entry in DEFAULT_DIRECTORY_BLACKLIST + user_blacklist:
        low = entry.lower()
        if low not in seen_lower:
            seen_lower.add(low)
            merged_blacklist.append(entry)

    blacklist_lower = {e.lower() for e in merged_blacklist}

    # Get relative path components from root to file
    abs_file = os.path.abspath(filepath)
    abs_root = os.path.abspath(root)
    try:
        rel = os.path.relpath(abs_file, abs_root)
    except ValueError:
        rel = abs_file
    parts = list(os.path.normpath(rel).split(os.sep))

    # Remove the filename itself
    if len(parts) > 0:
        filename = parts[-1]
        parts = parts[:-1]
    else:
        filename = os.path.basename(filepath)

    # Walk ancestors from closest to furthest (up to 5 levels)
    # parts[-1] is immediate parent, parts[-2] is grandparent, etc.
    if parts:
        parent_name = parts[-1]
        season_num = _is_season_dir(parent_name)

        if season_num is not None:
            # Parent is a pure season dir (e.g., "Season 1") → use grandparent
            if len(parts) >= 2:
                grandparent = parts[-2]
                if grandparent.lower() not in blacklist_lower:
                    return _extract_show_from_dir_name(grandparent)
            # Grandparent is blacklisted or doesn't exist → try further ancestors
            for i in range(len(parts) - 2, -1, -1):
                if i == len(parts) - 1:
                    continue  # skip the season dir itself
                candidate = parts[i]
                if candidate.lower() not in blacklist_lower:
                    return _extract_show_from_dir_name(candidate)
            # All ancestors blacklisted or missing → fall back to filename
            return _show_name_from_filename(filename)
        else:
            # Parent is not a pure season dir — check if it contains a season suffix
            # (e.g., "A Show Season 08" → extract "A Show")
            extracted = _extract_show_from_dir_name(parent_name)
            if extracted != parent_name:
                # Successfully stripped season suffix
                if extracted.lower() not in blacklist_lower:
                    return extracted

            # Use parent dir as show name if not blacklisted
            if parent_name.lower() not in blacklist_lower:
                return parent_name
            # Walk further ancestors (up to 5 levels)
            max_levels = min(len(parts), 5)
            for i in range(len(parts) - 1, max(len(parts) - max_levels - 1, -1), -1):
                candidate = parts[i]
                if candidate.lower() not in blacklist_lower:
                    return _extract_show_from_dir_name(candidate)
            # All blacklisted → fall back
            return _show_name_from_filename(filename)
    else:
        # File is directly under root — use root directory name
        root_name = os.path.basename(abs_root)
        if root_name and root_name.lower() not in blacklist_lower:
            return _extract_show_from_dir_name(root_name)
        return _show_name_from_filename(filename)


def _show_name_from_filename(filename: str) -> str:
    """Extract show name from the filename as a fallback.

    Strips extension and tries to get text before the season/episode marker.
    Returns 'Unknown' if nothing useful can be extracted.
    """
    stem = os.path.splitext(filename)[0]
    # Try to find text before any SxxExx or episode marker
    m = _SE_MARKER_RE.search(stem)
    if m:
        name = stem[: m.start()]
    else:
        # Try to get text before a plain episode number pattern
        m2 = re.search(r"\b\d{1,2}x\d{1,2}\b|\b\d{3,4}\b", stem)
        if m2:
            name = stem[: m2.start()]
        else:
            name = stem
    # Basic cleanup
    name = re.sub(r"[._-]+", " ", name).strip()
    return name if name else "Unknown"


def _strip_scene_tags(name: str, config: Optional[dict] = None) -> str:
    """Remove scene tags and group patterns from a name.

    Cleaning order:
    1. Group tag patterns (e.g., r"-\\w+$") applied FIRST on the raw string
       since these rely on original separators (e.g., dashes) being present.
    2. Separator normalization: dots and underscores → spaces, word-boundary hyphens → spaces.
    3. Scene tag removal: case-insensitive word-boundary matching of configured tags.

    Note: This means bracket-style group tags (e.g., [YIFY]) are removed regardless
    of separator, but dash-style group tags (e.g., -SPARKS) are only removed when the
    dash is present in the original filename. If the filename uses dots as separators
    (e.g., "Show.SPARKS"), the group name will only be removed if it happens to appear
    in the scene_tags strip list.

    Title casing is NOT applied here (done separately by _title_case).
    """
    if config is None:
        config = {}

    tags_config = get_scene_tags(config)
    strip_tags = tags_config["strip"]
    group_patterns = tags_config["group_tag_patterns"]

    # Step 0: Apply group tag patterns that rely on original separators (pre-normalization)
    # Step 0: Apply group tag patterns on pre-normalized string.
    # Safety: User-supplied patterns could have catastrophic backtracking.
    # Limit input length for user-regex processing to prevent ReDoS.
    pre_result = name
    MAX_REGEX_INPUT_LEN = 500
    for pat in group_patterns:
        try:
            if len(pre_result) <= MAX_REGEX_INPUT_LEN:
                pre_result = re.sub(pat, "", pre_result)
            # Skip regex on excessively long inputs to avoid ReDoS
        except (re.error, RecursionError):
            continue

    # Step 1: Separator normalization (dots, underscores, hyphens → spaces)
    result = re.sub(r"[._]+", " ", pre_result)
    # Hyphens used as separators: replace when surrounded by non-space
    result = re.sub(r"(?<=\w)-(?=\w)", " ", result)

    # Step 2: Scene tag removal (case-insensitive, word-boundary matching)
    for tag in strip_tags:
        # Escape special regex chars in the tag
        escaped = re.escape(tag)
        # Match the tag bounded by whitespace or string start/end
        pattern = r"(?<!\S)" + escaped + r"(?!\S)"
        result = re.sub(pattern, "", result, flags=re.IGNORECASE)

    # Collapse whitespace
    result = re.sub(r"\s+", " ", result).strip()
    return result


def _truncate_at_se_marker(name: str) -> str:
    """Truncate a show name at the first season/episode marker.

    Keeps everything before the earliest of a standalone season token
    (``S01``, ``Season 08``) or an SxxExx / NxNN marker, so only the real
    title is sent to a metadata provider.

    Example (post-separator-normalization input):
        "My Show S01 COMPLETE DSNP WEB DL DDP5 1 Atmos H 264" → "My Show"

    Conservative: if neither marker matches, the name is returned unchanged
    (a plain "My Show" stays "My Show"); if truncation would leave an empty
    string, the original name is returned.
    """
    season_match = _SE_TRUNCATE_RE.search(name)
    se_match = _SE_MARKER_RE.search(name)

    starts = [m.start() for m in (season_match, se_match) if m is not None]
    if not starts:
        return name

    cut = name[: min(starts)]
    # Clean up residual separators/whitespace left by the cut
    cut = re.sub(r"\s+", " ", cut).strip()
    cut = re.sub(r"^[.\s_-]+|[.\s_-]+$", "", cut)

    if not cut:
        return name
    return cut


def _extract_year(name: str) -> Tuple[str, Optional[int]]:
    """Extract a year (1950–2099) from the name if positioned before any SxxExx marker.

    Returns (cleaned_name_without_year, year) or (original_name, None).
    """
    # Find all year candidates
    year_matches = list(_YEAR_RE.finditer(name))
    if not year_matches:
        return name, None

    # Find position of first SxxExx / season-episode marker
    se_match = _SE_MARKER_RE.search(name)
    se_pos = se_match.start() if se_match else len(name)

    # Use the last year that appears before the SE marker
    valid_year = None
    valid_match = None
    for m in year_matches:
        if m.start() < se_pos:
            valid_year = int(m.group(1))
            valid_match = m

    if valid_year is None:
        return name, None

    # Remove the year from the name
    cleaned = name[: valid_match.start()] + name[valid_match.end():]
    # Clean up residual separators/whitespace around removed year
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    cleaned = re.sub(r"^[.\s_-]+|[.\s_-]+$", "", cleaned)

    return cleaned, valid_year


def _title_case(name: str) -> str:
    """Apply title casing with short-word and acronym preservation.

    Rules:
    - First word always capitalized
    - Short words (a, an, the, and, but, or, ...) lowercase when not first
    - Fully uppercase words of 2-5 chars preserved (acronyms like CSI, FBI)
    - All other words: first letter capitalized
    """
    if not name:
        return name

    words = name.split()
    result = []
    for i, word in enumerate(words):
        if not word:
            continue
        # Preserve acronyms: fully uppercase and 2-5 characters
        if word.isupper() and 2 <= len(word) <= 5:
            result.append(word)
        elif i == 0:
            # First word: always capitalize
            result.append(word[0].upper() + word[1:] if len(word) > 1 else word.upper())
        elif word.lower() in SHORT_WORDS:
            # Short word: lowercase
            result.append(word.lower())
        else:
            # Normal word: capitalize first letter
            result.append(word[0].upper() + word[1:] if len(word) > 1 else word.upper())

    return " ".join(result)


def _expand_template(template: str, tokens: dict) -> str:
    """Expand a template string with token values, supporting short aliases.

    Short aliases: {s}→season, {e}→episode, {t}→title, {y}→year
    Case-sensitive (lowercase only).

    When a token value is empty/None, substitutes empty string and cleans
    adjacent separators (removes dangling ' - ' or leading/trailing spaces).
    """
    # Map short aliases to long forms for lookup
    alias_map = {"s": "season", "e": "episode", "t": "title", "y": "year"}

    result = template
    # Replace all tokens (both long and short forms)
    all_tokens = set(re.findall(r"\{(\w+)\}", template))
    for token_name in all_tokens:
        # Resolve the canonical name
        canonical = alias_map.get(token_name, token_name)
        # Get value from tokens dict (try canonical first, then original name)
        value = tokens.get(canonical)
        if value is None:
            value = tokens.get(token_name)
        if value is None:
            value = ""
        result = result.replace("{" + token_name + "}", str(value))

    # Clean up dangling separators from empty tokens
    # Remove patterns like " - " that are left when a token is empty
    result = re.sub(r" - $", "", result)
    result = re.sub(r"^ - ", "", result)
    result = re.sub(r" -  - ", " - ", result)
    # Remove double spaces
    result = re.sub(r"  +", " ", result)
    # Remove space before extension (e.g., " .mkv" → ".mkv")
    result = re.sub(r"\s+(\.\w+)$", r"\1", result)
    # Remove trailing/leading separators
    result = result.strip()
    result = re.sub(r"^[.\s_-]+|[.\s_-]+(?=\.\w+$)", "", result)

    return result


def _classify_file(ext: str, junk_exts: set) -> str:
    """Classify a file by its extension into exactly one category.

    Args:
        ext: File extension (e.g., ".mkv"), will be compared case-insensitively.
        junk_exts: Set of extensions considered junk (lowercase, with leading dot).

    Returns:
        One of: "video", "subtitle", "junk", "unknown"
    """
    low = ext.lower()
    if low in VIDEO_EXTS:
        return "video"
    if low in SUBTITLE_EXTS:
        return "subtitle"
    if low in junk_exts:
        return "junk"
    return "unknown"


def _matches_exclude(relpath: str, patterns: List[str]) -> bool:
    """Check if a relative path matches any exclude glob pattern.

    Args:
        relpath: File path relative to the scan root.
        patterns: List of glob pattern strings.

    Returns:
        True if the relpath matches at least one pattern.
    """
    for pat in patterns:
        if fnmatch.fnmatch(relpath, pat):
            return True
        # Also try matching just the filename component
        basename = os.path.basename(relpath)
        if fnmatch.fnmatch(basename, pat):
            return True
    return False


REGEX_PATTERNS = [
    # support single episode and ranges like S01E01-02 or S01E01E02
    re.compile(
        r"[sS](?P<season>\d{1,2})[eE](?P<episode>\d{1,2})(?:[\s._-]*(?:[eE]|-)(?P<episode2>\d{1,2}))?"
    ),
    re.compile(r"(?P<season>\d{1,2})x(?P<episode>\d{1,2})(?:-(?P<episode2>\d{1,2}))?"),
    # Multi-digit shorthand (e.g., 101 = S1E01, 1002 = S10E02)
    # Exclude known non-episode patterns: resolutions (720, 1080, 2160), years (19xx, 20xx),
    # and codec numbers (264, 265)
    re.compile(r"(?<![0-9])(?!720|1080|2160|1920|264|265|(?:19|20)\d{2})(?P<season>\d{1,2})(?P<episode>\d{2})(?:-(?P<episode2>\d{2}))?(?![0-9p])"),
    # Loose number fallback: only match isolated 1-2 digit numbers preceded by a separator
    # (avoids matching inside years like 2023, resolutions like 720p, or codec tags like x264)
    re.compile(r"(?:^|[.\s_-])(?P<episode>\d{1,2})(?:[.\s_-]|$)"),
]

DEFAULT_TEMPLATE = "{show} - S{season}E{episode} - {title}{ext}"


def _extract_season_episodes(name: str) -> Optional[Tuple[int, list]]:
    """Return (season, [episodes...]) or None. Supports ranged episodes."""
    for rx in REGEX_PATTERNS:
        m = rx.search(name)
        if m:
            season = int(m.groupdict().get("season") or 0)
            ep1 = int(m.groupdict().get("episode") or 0)
            ep2 = m.groupdict().get("episode2")
            if ep2:
                try:
                    ep2 = int(ep2)
                    start = min(ep1, ep2)
                    end = max(ep1, ep2)
                    episodes = list(range(start, end + 1))
                except Exception:
                    episodes = [ep1]
            else:
                # try to detect explicit ranges like 01-02 after the match
                m2 = re.search(rf"{ep1:02d}[-–—](?P<e2>\d{{1,2}})", name)
                if m2:
                    try:
                        e2 = int(m2.group("e2"))
                        start = min(ep1, e2)
                        end = max(ep1, e2)
                        episodes = list(range(start, end + 1))
                    except Exception:
                        episodes = [ep1]
                else:
                    episodes = [ep1]
            return season, episodes
    return None


def _detect_part(name: str) -> Optional[int]:
    """Detect multi-part indicators like 'part 1', 'pt.1', 'CD1', 'disc 2'."""
    m = re.search(r"(?:part|pt|cd|disc)[\s._-]*(?P<p>\d{1,2})", name, re.I)
    if m:
        try:
            return int(m.group("p"))
        except Exception:
            return None
    return None


def _resolve_destination(dirpath: str, dst_basename: str, space_replacement=None):
    """Resolve final destination path, handling conflicts with counter suffixes.

    Returns (final_dst, conflict, intended_dst).
    """
    dst = os.path.join(dirpath, dst_basename)
    counter = 1
    final_dst = dst
    conflict = False
    intended_dst = None
    while os.path.exists(final_dst):
        if not conflict:
            conflict = True
            intended_dst = final_dst
        base2, ext2 = os.path.splitext(dst_basename)
        final_dst = os.path.join(dirpath, f"{base2} ({counter}){ext2}")
        counter += 1
    final_dst = sanitize_full_path(final_dst, space_replacement=space_replacement)
    return final_dst, conflict, intended_dst


def _strip_lang_suffix(name: str) -> Tuple[str, Optional[str]]:
    """Extract language suffix from subtitle stem. Returns (stem, '.en') or (stem, None)."""
    m = re.search(
        r"(?P<stem>.+?)(?:[._ ](?P<lang>[a-z]{2,3}(?:-[A-Z]{2})?))?$", name
    )
    if not m:
        return name, None
    stem = m.group("stem")
    lang = m.group("lang")
    if lang:
        return stem, f".{lang}"
    return stem, None


def _apply_name_resolver(show, year, name_resolver, resolver_cache):
    """Apply an optional name resolver to a cleaned show title.

    When ``name_resolver`` is None, returns ``show`` unchanged (default engine
    behaviour). Otherwise the resolver is called at most once per distinct
    ``show`` (memoized via ``resolver_cache``). Any exception is swallowed and
    a WARNING logged, falling back to the cleaned ``show``; an empty/None result
    also falls back to ``show``.
    """
    if name_resolver is None:
        return show
    if show in resolver_cache:
        return resolver_cache[show]
    try:
        resolved = name_resolver(show, year)
    except Exception as e:
        logging.getLogger(__name__).warning(
            "name resolver failed for %s: %s", show, e
        )
        resolved = show
    if not resolved:
        resolved = show
    resolver_cache[show] = resolved
    return resolved


def _scan_and_classify(root, config, exclude_patterns, junk_extensions, max_files=100000, name_resolver=None):
    """Scan root directory, classify files, and group them by type.

    Returns (groups, immediate, subtitles) where:
    - groups: dict of (dirpath, show, season, episode) → list of file dicts
    - immediate: list of file dicts (ranges/unknowns)
    - subtitles: list of subtitle file dicts

    max_files: Safety limit on total files processed to prevent resource exhaustion.
    """
    logger = logging.getLogger(__name__)

    groups = {}
    immediate = []
    subtitles = []
    resolver_cache = {}
    files_processed = 0

    for dirpath, dirs, files in os.walk(root):
        # Skip symlinked directories to prevent loops
        dirs[:] = [d for d in dirs if not os.path.islink(os.path.join(dirpath, d))]
        for fname in files:
            files_processed += 1
            if files_processed > max_files:
                logger.warning(
                    "File scan limit reached (%d files). Stopping scan.", max_files,
                )
                return groups, immediate, subtitles

            src = os.path.join(dirpath, fname)
            base, ext = os.path.splitext(fname)

            # Compute relative path for exclude matching
            try:
                relpath = os.path.relpath(src, root)
            except ValueError:
                relpath = fname

            # Exclude pattern check
            if exclude_patterns and _matches_exclude(relpath, exclude_patterns):
                logger.debug("Skipping excluded file: %s", relpath)
                continue

            # Classify file
            category = _classify_file(ext, junk_extensions)

            if category == "subtitle":
                subtitles.append({"src": src, "fname": fname, "ext": ext})
                continue
            if category != "video":
                continue

            # Resolve show name using the cleaning pipeline
            show_raw = _resolve_show_name(src, root, config)
            show_cleaned = _strip_scene_tags(show_raw, config)
            show_truncated = _truncate_at_se_marker(show_cleaned)
            show_no_year, year = _extract_year(show_truncated)
            show = _title_case(show_no_year)
            show = _apply_name_resolver(show, year, name_resolver, resolver_cache)

            se = _extract_season_episodes(fname)
            part = _detect_part(fname) or _detect_part(os.path.basename(dirpath))
            if se and len(se[1]) == 1 and se[0] > 0:
                season, episodes = se
                episode = episodes[0]
                key = (dirpath, show, season, episode)
                groups.setdefault(key, []).append(
                    {"src": src, "fname": fname, "ext": ext, "part": part, "year": year}
                )
            else:
                immediate.append({
                    "src": src, "fname": fname, "ext": ext,
                    "se": se, "show": show, "part": part, "year": year,
                })

    return groups, immediate, subtitles


def _process_groups(groups, provider_chain, template, fetch_titles, strict_windows, space_replacement):
    """Process grouped multipart files into plan entries.

    Returns (plan_entries, video_meta) where plan_entries is list of (src, dst) tuples.
    """
    plan = []
    video_meta = {}

    for (dirpath, show, season, episode), items in groups.items():
        # Sort by explicit part if present, else by filename
        items.sort(key=lambda it: (
            it["part"] is None,
            it["part"] if it["part"] is not None else it["fname"],
        ))
        # Assign missing part numbers sequentially
        existing = [it["part"] for it in items if it["part"] is not None]
        next_part = (max(existing) + 1) if existing else 1
        for it in items:
            if it["part"] is None:
                it["part"] = next_part
                next_part += 1

        # Fetch title once for the episode
        title = ""
        year_for_lookup = items[0].get("year") if items else None
        if fetch_titles:
            try:
                t = provider_chain.get_episode_title(show, season, episode, year=year_for_lookup)
                if t:
                    title = t
            except Exception:
                title = ""

        # Generate destinations for each part
        multi_parts = len(items) > 1
        for it in items:
            part = it["part"]
            year = it.get("year")
            if multi_parts:
                ttitle = f"{title} (Part {part})" if title else f"Part {part}"
            else:
                ttitle = title

            tokens = {
                "show": show or "Unknown",
                "season": f"{season:02d}",
                "episode": f"{episode:02d}",
                "title": ttitle,
                "year": str(year) if year else "",
                "ext": it["ext"],
            }
            new_name = _expand_template(template, tokens)
            dst_basename = sanitize_filename(
                new_name, strict_windows=strict_windows, space_replacement=space_replacement
            )
            dst = os.path.join(dirpath, dst_basename)
            if os.path.abspath(it["src"]) == os.path.abspath(dst):
                continue

            final_dst, conflict, intended_dst = _resolve_destination(
                dirpath, dst_basename, space_replacement
            )
            plan.append((it["src"], final_dst))
            video_meta[it["src"]] = {
                "dst": final_dst, "dir": dirpath, "show": show,
                "season": season, "episode": episode, "part": part,
                "conflict": conflict, "intended_dst": intended_dst,
            }

    return plan, video_meta


def _process_immediate(immediate, provider_chain, template, fetch_titles, strict_windows, space_replacement):
    """Process immediate (non-grouped) files into plan entries.

    Returns (plan_entries, video_meta).
    """
    plan = []
    video_meta = {}

    for meta in immediate:
        src = meta["src"]
        fname = meta["fname"]
        ext = meta["ext"]
        se = meta["se"]
        show = meta["show"]
        part = meta["part"]
        year = meta.get("year")

        if se:
            season, episodes = se
            episode_for_lookup = episodes[0] if episodes else 0
        else:
            season = 0
            episodes = []
            episode_for_lookup = 0

        title = ""
        if fetch_titles:
            try:
                if season > 0 and episode_for_lookup > 0:
                    t = provider_chain.get_episode_title(show, season, episode_for_lookup, year=year)
                    if t:
                        title = t
            except Exception:
                title = ""

        # Detect multipart siblings
        if part and episode_for_lookup > 0:
            sibling_count = 0
            try:
                for sfn in os.listdir(os.path.dirname(src)):
                    if sfn == fname:
                        continue
                    se2 = _extract_season_episodes(sfn)
                    if se2:
                        sseason, seps = se2
                        if sseason == season and episode_for_lookup in seps:
                            sibling_count += 1
                    else:
                        if _detect_part(sfn) is not None and str(episode_for_lookup).zfill(2) in sfn:
                            sibling_count += 1
            except Exception:
                sibling_count = 0
            if sibling_count > 0:
                title = f"{title} (Part {part})" if title else f"Part {part}"

        # Build episode token
        if se and len(episodes) > 0:
            if len(episodes) == 1:
                episode_token = f"{episodes[0]:02d}"
            else:
                episode_token = f"{min(episodes):02d}–{max(episodes):02d}"
        else:
            episode_token = "00"

        tokens = {
            "show": show or "Unknown",
            "season": f"{season:02d}",
            "episode": episode_token,
            "title": title,
            "year": str(year) if year else "",
            "ext": ext,
        }
        new_name = _expand_template(template, tokens)
        dst_basename = sanitize_filename(
            new_name, strict_windows=strict_windows, space_replacement=space_replacement
        )
        src_dir = os.path.dirname(src)
        dst = os.path.join(src_dir, dst_basename)
        if os.path.abspath(src) == os.path.abspath(dst):
            continue

        final_dst, conflict, intended_dst = _resolve_destination(
            src_dir, dst_basename, space_replacement
        )
        plan.append((src, final_dst))
        video_meta[src] = {
            "dst": final_dst, "dir": src_dir, "show": show,
            "season": season, "episodes": episodes, "part": part,
            "conflict": conflict, "intended_dst": intended_dst,
        }

    return plan, video_meta


def _pair_subtitles(subtitles, video_meta, strict_windows):
    """Pair subtitle files to their matching video targets.

    Returns list of (src, dst) tuples for subtitle renames.
    """
    plan = []

    # Build lookup of videos by directory
    videos_by_dir = {}
    for vsrc, vinfo in video_meta.items():
        d = vinfo["dir"]
        videos_by_dir.setdefault(d, []).append({
            "src": vsrc, "dst": vinfo["dst"],
            "part": vinfo.get("part"), "season": vinfo.get("season"),
            "episodes": vinfo.get("episodes"),
        })

    for sub in subtitles:
        ssrc = sub["src"]
        sfname = sub["fname"]
        sext = sub["ext"]
        sstem, slang = _strip_lang_suffix(os.path.splitext(sfname)[0])
        sdir = os.path.dirname(ssrc)
        matched = None
        candidates = videos_by_dir.get(sdir, [])

        # Try exact stem match
        for c in candidates:
            vbase = os.path.splitext(os.path.basename(c["src"]))[0]
            if sstem == vbase or sstem.startswith(vbase) or vbase.startswith(sstem):
                matched = c
                break

        # Fallback: match by episode/part
        if not matched:
            sep = _extract_season_episodes(sfname)
            part = _detect_part(sfname)
            if sep:
                sseason, seps = sep
                sepe = seps[0] if seps else None
                for c in candidates:
                    if (c.get("season") == sseason and c.get("episodes")
                            and sepe in c.get("episodes", [])):
                        matched = c
                        break
            if not matched and part:
                for c in candidates:
                    if c.get("part") == part:
                        matched = c
                        break

        if matched:
            vdst = matched["dst"]
            base = os.path.splitext(os.path.basename(vdst))[0]
            dst_basename = f"{base}{slang}{sext}" if slang else f"{base}{sext}"
            dst_basename = sanitize_filename(dst_basename, strict_windows=strict_windows)
            sdst = os.path.join(sdir, dst_basename)
            sdst = sanitize_full_path(sdst)
            if not any(os.path.abspath(ssrc) == os.path.abspath(p[0]) for p in plan):
                plan.append((ssrc, sdst))

    return plan


def plan_renames(
    root: str,
    template: str = DEFAULT_TEMPLATE,
    cache: DiskCache | None = None,
    providers: List = None,
    space_replacement: str | None = None,
    exclude_patterns: List[str] | None = None,
    fetch_titles: bool = True,
    config: dict | None = None,
    strict_windows: bool = False,
    junk_extensions: set | None = None,
    name_resolver=None,
) -> List[Tuple[str, str]]:
    """Scan root recursively and create a plan list of (src_abs, dst_abs) without performing actions.

    Args:
        root: Directory to scan recursively.
        template: Filename template with tokens like {show}, {season}, {episode}, {title}, {ext}.
        cache: Disk cache instance (auto-created if None).
        providers: List of metadata providers (defaults to TVMaze).
        space_replacement: "underscore" to replace spaces in filenames, or None to keep spaces.
        exclude_patterns: Glob patterns for files to skip.
        fetch_titles: If False, skip all provider lookups ({title} becomes empty).
        config: Parsed TOML config dict for extraction/cleaning settings.
        strict_windows: Pass through to sanitizer for Windows-compatible names.
        junk_extensions: Set of lowercase extensions considered junk (for classification only).
        name_resolver: Optional callable (cleaned_show, year) -> str used to
            substitute the cleaned show title before grouping/title lookup. When
            None (the default), behaviour is unchanged.
    """
    if config is None:
        config = {}
    if exclude_patterns is None:
        exclude_patterns = []
    if junk_extensions is None:
        junk_extensions = set(e.lower() for e in get_junk_extensions(config))

    if cache is None:
        cache = DiskCache(os.path.join(root, ".tvrenamer_cache.json"))
    if providers is None:
        providers = [TVMazeProvider(cache)]
    if isinstance(providers, list):
        provider_chain = ProviderChain(providers)
    else:
        provider_chain = providers

    # 1. Scan and classify files
    groups, immediate, subtitles = _scan_and_classify(
        root, config, exclude_patterns, junk_extensions, name_resolver=name_resolver
    )

    # 2. Process grouped multipart files
    group_plan, video_meta = _process_groups(
        groups, provider_chain, template, fetch_titles, strict_windows, space_replacement
    )

    # 3. Process immediate (non-grouped) files
    imm_plan, imm_meta = _process_immediate(
        immediate, provider_chain, template, fetch_titles, strict_windows, space_replacement
    )
    video_meta.update(imm_meta)

    # 4. Pair subtitles to video targets
    sub_plan = _pair_subtitles(subtitles, video_meta, strict_windows)

    return group_plan + imm_plan + sub_plan


def perform_transaction_for_plan(
    root: str,
    plan: List[Tuple[str, str]],
    execute: bool = False,
    journal_dir: Optional[str] = None,
) -> Tuple[str, List[Tuple[str, str]]]:
    """Given a plan, write journal and optionally execute. Returns (journal_path, plan).

    On successful commit, writes a history file for undo support.
    """
    if journal_dir is None:
        journal_dir = root
    journal = build_transaction(plan, run_id=logging_setup.CURRENT_RUN_ID)
    journal_path = write_journal_atomically(journal, journal_dir)
    if execute:
        execute_transaction(journal_path)
        # Post-commit: write history file for undo support
        try:
            committed_journal = _read_journal(journal_path)
            write_history_file(committed_journal, journal_dir)
        except Exception as e:
            logging.getLogger(__name__).error(
                "Failed to write history file: %s", e
            )
    return journal_path, plan
