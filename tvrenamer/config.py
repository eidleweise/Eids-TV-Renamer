import os
from typing import Dict, List, Optional

try:
    import tomllib as _toml  # Python 3.11+
except Exception:
    try:
        import toml as _toml  # type: ignore
    except Exception:
        _toml = None


# --- Default values ---

DEFAULT_DIRECTORY_BLACKLIST: List[str] = [
    "Downloads", "TV Shows", "TV", "Completed",
    "Desktop", "Videos", "Media", "Series", "Shows",
]

DEFAULT_SCENE_TAGS_STRIP: List[str] = [
    "PROPER", "REPACK", "RERIP", "INTERNAL", "WEB-DL", "WEBRip",
    "HDTV", "BluRay", "BDRip", "x264", "x265", "H.264", "H.265",
    "HEVC", "AAC", "DTS", "720p", "1080p", "2160p", "4K",
]

DEFAULT_GROUP_TAG_PATTERNS: List[str] = [
    r"\[.*?\]",
    r"-\w+$",
]

DEFAULT_JUNK_EXTENSIONS: List[str] = [
    ".nfo", ".txt", ".url", ".jpg", ".jpeg", ".png", ".bmp", ".tbn",
]


def find_config_path(path: Optional[str] = None, root: Optional[str] = None) -> Optional[str]:
    """Return the first existing config path from candidates or None.

    Search order: explicit path, root/.tvrenamer.toml, ~/.tvrenamer.toml
    """
    candidates = []
    if path:
        candidates.append(path)
    if root:
        candidates.append(os.path.join(root, ".tvrenamer.toml"))
    home = os.path.expanduser("~")
    candidates.append(os.path.join(home, ".tvrenamer.toml"))
    for p in candidates:
        if p and os.path.exists(p):
            return p
    return None


def load_config(path: Optional[str] = None, root: Optional[str] = None) -> dict:
    """Load TOML config from given path or root/.tvrenamer.toml or ~/.tvrenamer.toml.

    Returns empty dict if no config found or parser unavailable.
    """
    cfg_path = find_config_path(path, root)
    if not cfg_path:
        return {}
    if _toml is None:
        return {}
    try:
        with open(cfg_path, "rb") as f:
            return _toml.load(f)
    except Exception:
        return {}


# --- Section accessor functions ---


def get_directory_blacklist(config: dict) -> List[str]:
    """Extract directory_blacklist from [path_extraction] section.

    Returns the configured list if present, otherwise the default blacklist.
    """
    section = config.get("path_extraction", {})
    blacklist = section.get("directory_blacklist")
    if blacklist is None:
        return list(DEFAULT_DIRECTORY_BLACKLIST)
    if not isinstance(blacklist, list):
        return list(DEFAULT_DIRECTORY_BLACKLIST)
    return [str(entry) for entry in blacklist]


def get_scene_tags(config: dict) -> Dict[str, List[str]]:
    """Extract scene tag configuration from [scene_tags] section.

    Returns a dict with 'strip' and 'group_tag_patterns' lists.
    Applies validation: strip max 100 entries (each 1-30 chars),
    group_tag_patterns max 20 entries (each 1-200 chars).
    Returns defaults when section is absent.
    """
    section = config.get("scene_tags")
    if section is None:
        return {
            "strip": list(DEFAULT_SCENE_TAGS_STRIP),
            "group_tag_patterns": list(DEFAULT_GROUP_TAG_PATTERNS),
        }

    # Parse strip list
    strip_raw = section.get("strip")
    if strip_raw is None:
        strip = list(DEFAULT_SCENE_TAGS_STRIP)
    elif not isinstance(strip_raw, list):
        strip = list(DEFAULT_SCENE_TAGS_STRIP)
    else:
        # Validate: max 100 entries, each 1-30 characters
        strip = []
        for entry in strip_raw[:100]:
            s = str(entry)
            if 1 <= len(s) <= 30:
                strip.append(s)

    # Parse group_tag_patterns list
    patterns_raw = section.get("group_tag_patterns")
    if patterns_raw is None:
        patterns = list(DEFAULT_GROUP_TAG_PATTERNS)
    elif not isinstance(patterns_raw, list):
        patterns = list(DEFAULT_GROUP_TAG_PATTERNS)
    else:
        # Validate: max 20 entries, each 1-200 characters, must compile as valid regex
        import re
        patterns = []
        for entry in patterns_raw[:20]:
            s = str(entry)
            if 1 <= len(s) <= 200:
                try:
                    re.compile(s)
                    patterns.append(s)
                except re.error:
                    # Skip invalid regex patterns
                    pass

    return {
        "strip": strip,
        "group_tag_patterns": patterns,
    }


def get_junk_extensions(config: dict) -> List[str]:
    """Extract junk file extensions from [junk] section.

    Returns the configured extensions list if present (or defaults if absent/empty).
    Per Requirement 10.3: if section is absent OR extensions list is empty,
    use the default extensions.
    """
    section = config.get("junk", {})
    extensions = section.get("extensions")
    if extensions is None or not isinstance(extensions, list) or len(extensions) == 0:
        return list(DEFAULT_JUNK_EXTENSIONS)
    return [str(ext) for ext in extensions]


def get_defaults(config: dict) -> Dict[str, object]:
    """Extract values from the [defaults] section.

    Returns a dict with:
      - fetch_titles: bool (default True)
      - strict_windows: bool (default False)
      - exclude_patterns: list of str (default [])
      - space_replacement: str (default "")
    """
    section = config.get("defaults", {})

    fetch_titles = section.get("fetch_titles")
    if not isinstance(fetch_titles, bool):
        fetch_titles = True

    strict_windows = section.get("strict_windows")
    if not isinstance(strict_windows, bool):
        strict_windows = False

    exclude_patterns = section.get("exclude_patterns")
    if not isinstance(exclude_patterns, list):
        exclude_patterns = []
    else:
        exclude_patterns = [str(p) for p in exclude_patterns]

    space_replacement = section.get("space_replacement")
    if not isinstance(space_replacement, str):
        space_replacement = ""

    return {
        "fetch_titles": fetch_titles,
        "strict_windows": strict_windows,
        "exclude_patterns": exclude_patterns,
        "space_replacement": space_replacement,
    }


def get_provider_tvmaze(config: dict) -> Dict[str, object]:
    """Extract TVMaze provider settings from [provider.tvmaze] section.

    Returns a dict with:
      - prefetch_seasons: bool (default False)
    """
    provider_section = config.get("provider", {})
    tvmaze_section = provider_section.get("tvmaze", {})

    prefetch_seasons = tvmaze_section.get("prefetch_seasons")
    if not isinstance(prefetch_seasons, bool):
        prefetch_seasons = False

    return {
        "prefetch_seasons": prefetch_seasons,
    }
