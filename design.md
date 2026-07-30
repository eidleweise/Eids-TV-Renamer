# Media File Renamer & Organizer — System Design Document

A robust, flexible Python utility designed to recursively scan, clean, rename, and organize TV show episode files and their associated subtitles, with support for online metadata fetching (TVMaze) and clutter file cleanup.

---

## 1. System Architecture & Core Pipeline

The application processes media files through a 5-stage sequential pipeline:

```
┌─────────────────┐
│ File Scanner    │   Recursively discovers files & classifies (Video, Subtitle, Junk)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Pattern         │   Path-aware Regex Cascade extracts Show Name, Season, & Episode
│ Extractor       │  (Handles single-file scene tags & folder structures like "Show/Season 1/Ep1")
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Metadata        │   Queries TVMaze REST API for official episode titles
│ Engine          │  (Uses local memory caching to minimize network calls)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Formatter &     │   Applies user pattern template ({show} - S{season}E{episode} - {title})
│ Subtitle Match  │  and pairs .srt/.vtt files with language tag retention (.en.srt)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│ Renamer Engine  │  Generates side-by-side dry-run preview, handles selective execution,
│ & Cleanup       │  writes JSON undo history, and purges/trashes junk clutter
└─────────────────┘
```

---

## 2. Interface Specifications (Dual-Mode Design)

The application supports both **interactive wizard execution** (for manual users) and **non-interactive CLI flags** (for scripting, cron jobs, and automation).

### 2.1 Mode Determination & Option Precedence

The CLI uses a clear precedence chain for every option: **CLI flag > config file > interactive prompt > hardcoded default**.

For the target path specifically:

```
1. --path /some/dir              → uses that directory
2. config: defaults.path = "~/"  → uses the config path (with ~ expansion)
3. --interactive (no path found) → prompts user: "Target directory to scan:"
4. none of the above             → defaults to current directory (.)
```

This applies uniformly to all options (template, execute, providers, etc.):
- If a CLI flag is provided, it always wins.
- If not, the value from `.tvrenamer.toml` is used (if loaded).
- In interactive mode, the user is prompted for any essential missing values (currently: target path).
- Finally, hardcoded defaults apply for anything still unset.

```python
# Mode selection (simplified)
if args.interactive:
    # prompt for missing essentials (path, etc.)
    pass
# Regardless of mode, precedence is: CLI flag > config > default
```

### 2.2 CLI Command-Line Arguments

| Flag | Short | Default | Description |
|------|-------|---------|-------------|
| `--path` | `-p` | `./` | Target directory to scan recursively |
| `--config` | `-c` | | Path to a TOML config file to load defaults from |
| `--template` | `-t` | `"{show} - S{season}E{episode} - {title}{ext}"` | Renaming format template |
| `--providers` | | `tvmaze,wikidata,wikipedia` | Comma-separated provider query order |
| `--fetch-titles` | `-f` | `True` | Fetch official episode titles from providers |
| `--no-fetch-titles` | | `False` | Skip online API queries; clean local text only |
| `--execute` | `-x` | `False` | Perform real disk rename (Default is Dry-Run Preview) |
| `--space-replacement` | | | Replace spaces in filenames: `underscore` or `none` |
| `--clean-junk` | | `False` | Permanently delete junk files (.nfo, .txt, .url, etc.) |
| `--trash-junk` | | `False` | Move junk files into a `.trash/` directory instead of deleting |
| `--strict-windows` | | `False` | Activate Windows-compatible filename sanitization |
| `--exclude` | | | Glob pattern for files to skip (repeatable, e.g., `"*sample*"`) |
| `--undo` | | | Path to a JSON history file; reverses all renames recorded in it |
| `--verbose` | `-v` | `False` | Show detailed output including API responses and match reasoning |
| `--quiet` | `-q` | `False` | Suppress all output except errors (useful for scripting/cron) |
| `--no-color` | | `False` | Disable ANSI colour output |
| `--resume` | | `False` | Resume pending transaction journals |
| `--rollback` | | `False` | Rollback pending/failed transaction journals |
| `--log-file` | | `<target>/.tvrenamer.log` | Path to write structured log file |
| `--log-level` | | `INFO` | Logging level: DEBUG, INFO, WARN, ERROR |
| `--interactive` | `-i` | `False` | Force the interactive wizard even if flags are passed |

All CLI flags override their corresponding config file values. Config keys match CLI flag names (e.g., `defaults.path` ↔ `--path`, `defaults.template` ↔ `--template`).

### 2.3 Configuration File Support

For users who always use the same template and options, a `.tvrenamer.toml` config file can be placed in the user's home directory or the target media directory. CLI flags override config file values. Config keys match their CLI flag names.

```toml
[defaults]
path = "/home/user/Videos/TV Shows/"
template = "{show} - S{season}E{episode} - {title}{ext}"
execute = false
fetch_titles = true
strict_windows = false
space_replacement = "underscore"
exclude_patterns = ["*sample*"]

[providers]
order = ["tvmaze", "wikidata", "wikipedia"]

[junk]
extensions = [".nfo", ".txt", ".url", ".jpg", ".png", ".sfv", ".md"]

[scene_tags]
# Tags stripped from filenames during show name cleaning
strip = [
    "PROPER", "REPACK", "RERIP", "INTERNAL",
    "WEB-DL", "WEBRip", "HDTV", "BluRay", "BDRip",
    "x264", "x265", "H.264", "H.265", "HEVC", "AAC", "DTS",
    "720p", "1080p", "2160p", "4K",
]
# Regex patterns for group tags like [GroupName] or -GroupName at end of filename
group_tag_patterns = [
    "\\[.*?\\]",
    "-\\w+$",
]

[path_extraction]
# Additional directory names to ignore when resolving show names
directory_blacklist = ["Incoming", "Unsorted"]
```

### 2.4 Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success — all operations completed |
| `1` | No media files found in target directory |
| `2` | API errors (network failure, rate limit exceeded) |
| `3` | File operation errors (permission denied, disk full) |
| `4` | Invalid arguments or configuration |

---

## 3. File Classification & Pattern Extraction

### 3.1 File Type Categories

| Category | File Extensions | Handling Strategy |
|----------|----------------|-------------------|
| Video Files | `.mkv`, `.mp4`, `.avi`, `.m4v`, `.ts`, `.wmv`, `.mov` | Process through extraction & renaming pipeline |
| Subtitles | `.srt`, `.sub`, `.vtt`, `.ass`, `.idx`, `.smi` | Match to primary video episode ID; apply new name + preserve language tags |
| Junk / Clutter | `.nfo`, `.txt`, `.url`, `.jpg`, `.png`, `.sfv`, `.md` | Flagged for review; can be safely purged or trashed |
| Unknown | All other extensions | Left untouched by default |

> **Note:** The junk classification applies to files discovered *within the scanned media directory*, not to the tool's own project files. A `.md` file inside a media folder is almost certainly a leftover release note, not documentation you care about. The junk extension list is user-configurable via the config file.

### 3.2 Regex Pattern Cascade (Waterfall Extraction)

The extractor runs filenames through a prioritized list of patterns from most specific to most forgiving:

```python
REGEX_PATTERNS = [
    # Standard Scene: S01E01 / s1e2
    r"[sS](?P<season>\d{1,2})[eE](?P<episode>\d{1,2})",

    # Multi-Episode: S01E01E02 / S01E01-E03
    r"[sS](?P<season>\d{1,2})[eE](?P<episode>\d{1,2})(?:[eE-]+(?P<episode_end>\d{1,2}))+",

    # Alternate Separator: 1x01 / 01x02
    r"(?P<season>\d{1,2})x(?P<episode>\d{1,2})",

    # Text Explicit: EP01 / Episode 02
    r"(?:EP|EPISODE)[.\s_-]*(?P<episode>\d{1,2})",

    # Absolute Episode (Anime): 347, 1024 (three+ digits treated as absolute)
    r"\b(?P<episode>\d{3,4})\b",

    # Multi-digit Shorthand: 101, 1002 (only applied when not anime mode)
    r"\b(?P<season>\d{1,2})(?P<episode>\d{2})\b",

    # Loose Number (Folder Fallback): 01.mp4 / Episode1.mp4
    r"(?P<episode>\d{1,2})"
]
```

**Multi-episode handling:** When a range is detected (e.g., S01E01E02), the tool uses the *first* episode number for the TVMaze title lookup and names the file accordingly: `Show - S01E01–E02 - Pilot.mkv`. Additionally, the tool groups multipart (split) files that map to the same show/season/episode and renames each part with an explicit part suffix. For example:

- `Show.S01E05.part1.mkv` and `Show.S01E05.part2.mkv`  →  `Show - S01E05 - Title (Part 1).mkv` and `Show - S01E05 - Title (Part 2).mkv`

When part numbers are missing, the tool assigns sequential Part N values deterministically (sorted by filename). Single-file multi-episode ranges remain a single renamed file using an episode range token (e.g., `S01E01–02`) and the title lookup still uses the first episode in the range. This grouping behavior is the default; a future CLI/config flag may allow altering it (e.g., force-range-only, merge-parts, or split-and-reencode options).

**Absolute numbering (Anime):** Files with 3–4 digit episode numbers and no explicit season marker are treated as absolute-numbered episodes. The tool queries TVMaze using the absolute episode number where supported, or falls back to a no-title rename.

### 3.3 Path-Aware Extraction Strategy

If the filename lacks a Show Name or Season number (e.g., `/My Show/Season 1/Ep01.mp4`):

1. **Filename Inspection:** Search for Show Name and SxxExx tag in the file string.
2. **Parent Directory Inspection:** If Season is missing, inspect the immediate parent directory name for `Season X` or `S01`.
3. **Grandparent Directory Inspection:** If the parent folder is a Season folder, extract the Show Name from the grandparent folder.
4. **Season Suffix Stripping:** If a directory name contains both a show name and a season suffix (e.g., `The Rookie Season 08`), the season portion is stripped and the remaining text used as the show name. This handles common media library layouts where each season has its own folder named `{Show} Season {N}`.
5. **Root Directory Fallback:** When the scan root IS the show folder (files are at `root/Season N/file.mkv` with no grandparent), the root directory's own name is used as the show name (with season suffix stripping applied).
6. **Directory Blacklist Guard:** Ignore generic folder names like `Downloads`, `TV Shows`, `Completed`, or `Desktop`.

### 3.4 Show Name Cleaning

Raw show names extracted from filenames contain scene release cruft that must be stripped before API queries or use in the final filename:

1. **Separator Normalization:** Replace `.`, `_`, and `-` used as word separators with spaces.
2. **Scene Tag Removal:** Strip known quality/codec/source tags (configurable via `[scene_tags]` in config).
3. **Group Tag Removal:** Remove release group identifiers like `[GroupName]` or `-GROUPNAME` at the end.
4. **Title Casing:** Apply title case to the cleaned result (e.g., `the.wire` → `The Wire`).
5. **Year Preservation:** If a year is present (e.g., `Battlestar Galactica 2003`), preserve it for disambiguation during API lookup but optionally exclude it from the final filename via the `{year}` token.

---

## 4. Metadata Lookup & Template Engine

### 4.1 TVMaze Integration

- **Show Query Endpoint:** `GET https://api.tvmaze.com/singlesearch/shows?q={cleaned_show_name}`
- **Episode Query Endpoint:** `GET https://api.tvmaze.com/shows/{show_id}/episodebynumber?season={s}&number={e}`
- **Seasons / Episodes Prefetching:** When a show is first resolved, the engine may optionally prefetch season/episode listings using `GET https://api.tvmaze.com/shows/{show_id}/seasons` and/or `GET https://api.tvmaze.com/shows/{show_id}/episodes` to populate the local run cache and reduce per-episode lookups. This prefetching is controlled by a provider config flag (e.g., `provider.tvmaze.prefetch_seasons = true`) and is subject to rate-limiter constraints.
- **Per-Provider HTTP Headers:** The provider layer supports custom headers per provider (useful for User-Agent, Accept-Language, or Authorization tokens). Example config:

```toml
[provider.tvmaze]
enabled = true
headers = { "User-Agent" = "tvrenamer/1.0 (+https://example.org)" }
provider.tvmaze.prefetch_seasons = true
```

Headers are applied to all requests to the provider and may be configured to redact values in logs. Providers that require special Accept or Authorization behaviour can be configured without code changes.

- **Wikidata SPARQL Fallback:** When TVMaze returns no match (and caching is absent/expired), the metadata engine can optionally fall back to a Wikidata SPARQL lookup to resolve episode titles and season/episode mappings. The SPARQL fallback uses the public endpoint `https://query.wikidata.org/sparql` and should send a descriptive `User-Agent` and `Accept: application/sparql-results+json`. Example SPARQL pattern (simplified):

```
SELECT ?episode ?episodeLabel ?seasonNum ?episodeNum WHERE {
  ?episode wdt:P31 wd:Q21191270;            # instance of TV episode
           wdt:P179 ?series;                  # part of series
           wdt:P1545 ?episodeNumLabel.        # episode number (when available)
  ?series rdfs:label "{show_name}"@en.
  SERVICE wikibase:label { bd:serviceParam wikibase:language "en". }
}
```

The SPARQL fallback must be rate-limited independently and respect the endpoint's usage guidance. Results are normalized into the same internal Show/Episode structure before caching. Use Wikidata only as a best-effort fallback — prefer TVMaze for episode-level accuracy when available.

- **Memory Caching:** Results are cached in a local execution dictionary `cache[provider][show_name][season][episode]` to prevent redundant API calls for multi-episode series. Prefetched seasons/episodes populate this cache eagerly when enabled.
- **Persistent Disk Cache:** A configurable JSON cache (`.tvrenamer_cache.json`) is written to the target directory (preferred) or the user's home directory. Cache entries include timestamps and source provider metadata; default TTL is 7 days. Cache size is capped (configurable, default 1000 entries) and the cache implements LRU eviction (including on load). Concurrent runs obtain a lightweight file lock (`fcntl.flock`) to avoid corruption.
- **Stale-While-Revalidate & Offline Mode:** Cached entries may be used when a provider is unreachable. The tool supports 'stale-while-revalidate' behavior: serve cached results immediately and attempt a background refresh to update the cache. If refreshing fails repeatedly (3 consecutive attempts per entry), the stale data stops being refreshed to avoid infinite retries. If the circuit breaker opens (5 consecutive provider failures), the system flips into offline mode for the remainder of the run.
- **Cache Write Throttling:** Background cache persists on read operations (for access-time updates) are throttled to at most once per 60 seconds to prevent disk I/O storms when processing many files.
- **Rate Limiting & Backoff:** A per-provider leaky-bucket limiter enforces configurable rates (defaults tuned for TVMaze: 20 req / 10s). SPARQL and other public endpoints may have separate, stricter defaults. On transient errors (429, 5xx, network), use exponential backoff with full jitter, respect `Retry-After` when present, and cap retries (default 5). Batch lookups where provider endpoints allow (e.g., bulk show queries) and introduce small randomized delays to reduce bursts. A circuit-breaker opens after N consecutive failures and forces offline-mode for a cooldown period.
- **Cache Migration & Integrity:** Cache files include a `_meta` entry with a `version` integer (currently 1) and a `checksum` (SHA-256 hex digest over the sorted data payload). On load: if the version is outdated, all data is discarded; if the checksum doesn't match, the file is rotated to `.tvrenamer_cache.json.corrupt.{epoch}` and the cache starts fresh. All cache writes are atomic (write-to-temp + rename via shared `atomic_write_json` utility). Symlinked cache files are rejected to prevent poisoning.
- **Offline Fallback:** If all configured providers fail or return no match and no cache entry exists, the system falls back to `{show} - S{season}E{episode}{ext}` without breaking execution. Providers may be individually disabled in config to avoid unwanted network calls (e.g., disable SPARQL if policy forbids).
- **Special Episodes:** Season 0 episodes (specials) are supported. If the extractor identifies a special (e.g., `S00E01`), it queries providers under season 0 where supported. If no title is found, the file is renamed without a title rather than skipped.

### 4.2 Provider Architecture (Future Extension)

The metadata engine is designed as a pluggable interface:

```python
class MetadataProvider(ABC):
    @abstractmethod
    def search_show(self, name: str, year: int | None = None) -> Show | None: ...

    @abstractmethod
    def get_episode(self, show_id: str, season: int, episode: int) -> Episode | None: ...
```

Only TVMaze is implemented initially, but this structure allows adding TMDB or TheTVDB providers later without changing the pipeline.

All providers inherit from `BaseNetworkProvider` which provides shared HTTP fetch logic with retry, exponential backoff (full jitter), rate limiting (token bucket), and circuit breaking. Each provider configures its own retry count (TVMaze: 5, others: 3) and backoff parameters.

### 4.3 Wikipedia & Wikidata Integration

**Wikipedia Provider Endpoints:**

- **Show Search (OpenSearch):** `GET https://en.wikipedia.org/w/api.php?action=opensearch&limit=1&search={show_name}&format=json`
  Returns a matching Wikipedia page title for the show.
- **Page Summary:** `GET https://en.wikipedia.org/api/rest_v1/page/summary/{title}`
  Fetches the page summary to extract episode information via heuristic parsing.

The Wikipedia provider attempts to find episode titles by searching for pages matching patterns like "Show (season N)", "Show season N", or "List of Show episodes". It parses the page content for episode tables or structured data.

**Wikidata Provider Endpoints:**

- **Entity Search:** `GET https://www.wikidata.org/w/api.php?action=wbsearchentities&format=json&language=en&limit=1&search={show_name}`
  Finds the Wikidata entity ID for a show.
- **Entity Data:** `GET https://www.wikidata.org/wiki/Special:EntityData/{id}.json`
  Fetches full entity data for a resolved show.
- **SPARQL Query:** `GET https://query.wikidata.org/sparql?query={sparql}`
  Executes a SPARQL query to find episode labels matching show/season/episode.

The Wikidata provider uses two strategies:
1. Entity search + data retrieval for show-level information
2. SPARQL queries as a fallback to find specific episode titles by matching labels

SPARQL inputs are escaped to prevent injection (backslash, quotes, newlines, tabs). Both providers respect the Wikimedia User-Agent policy and use descriptive User-Agent headers.

### 4.4 No-registration Providers

- TVmaze — public API; most endpoints require no API key and are a good default for anonymous metadata lookup.
- Wikipedia / Wikidata — open APIs for titles, summaries, release dates, and external identifiers.
- XMLTV / Public EPG feeds — many providers publish TV listings without authentication.
- Public broadcaster APIs — some networks expose schedules and metadata without registration (varies by country).
- Web scraping — possible for sites that lack APIs; follow terms of service and rate-limit responsibly.

These providers can be used as lightweight, no-registration fallbacks in the metadata provider layer.

### Provider Ordering & Configuration

The tool exposes provider ordering so users can control which providers are queried first. Default order is `tvmaze -> wikidata -> wikipedia`, but users can prefer Wikidata/Wikipedia before TVMaze when working with local or crowd-sourced data. Providers are configured independently with enable flags, per-provider headers, rate-limits, and optional behavioral flags (e.g., seasons prefetch).

Configuration example (`.tvrenamer.toml`):

[providers]
order = ["tvmaze", "wikidata", "wikipedia"]

[provider.tvmaze]
enabled = true
headers = { "User-Agent" = "tvrenamer/1.0 (+https://example.org)" }
prefetch_seasons = true
rate_limit = { requests = 20, per_seconds = 10 }

[provider.wikidata]
enabled = true
# Optional: toggle SPARQL fallback and headers
use_sparql_fallback = true
headers = { "User-Agent" = "tvrenamer/1.0 (+https://example.org)", "Accept" = "application/sparql-results+json" }

[provider.wikipedia]
enabled = true

Behavior:
- The engine builds a ProviderChain in the configured order and queries each provider in turn for a show or episode title.
- Providers may expose provider-specific options (headers, prefetching, per-provider rate-limits, and SPARQL fallback toggles) to allow fine-grained control without code changes.
- The first provider to return a non-empty title wins; subsequent providers are not queried for that item unless the requesting logic explicitly asks for merged/combined metadata.
- Providers are consulted only when necessary (season+episode identified) and the cache is consulted first to avoid unnecessary network calls.
- Rate-limiting, retry, and circuit-breaker settings are provider-specific and driven from configuration; SPARQL or other public endpoints may require stricter defaults.

This lets users tune accuracy vs. friction (e.g., prefer Wikidata/Wikipedia for more open data sources, or TMDb/TVMaze for richer episode metadata). It also enables compliance with provider usage policies by allowing per-provider header customization and rate-limit configuration.

### 4.3 Formatting Tokens

Users can define custom patterns using template tokens:

| Token | Description |
|-------|-------------|
| `{show}` | Official or cleaned show name |
| `{season}` / `{s}` | Two-digit padded season number (01) |
| `{episode}` / `{e}` | Two-digit padded episode number (02) |
| `{title}` / `{t}` | Official episode title (e.g., "Pilot") |
| `{year}` / `{y}` | Show's premiere year (for disambiguation) |
| `{ext}` | Original file extension with dot (.mkv) |

**Example:**

```
"{show} - S{season}E{episode} - {title}{ext}" → TV Show - S01E01 - Pilot.mkv
"{show} ({year}) - S{season}E{episode}{ext}"   → Battlestar Galactica (2003) - S01E01.mkv
```

Configuration: space replacement behavior

- `defaults.space_replacement` controls whether spaces in the *generated filename* are replaced. Supported value: `"underscore"` (replace spaces with `_`), or unset/empty to preserve spaces.
- Important: space replacement is applied only to the final filename component (the basename). Directory names are left human-readable and are not converted to underscores.

Example config snippet:

```toml
[defaults]
template = "{show}-S{season}E{episode}-{title}{ext}"
# replace spaces in the filename only (directories keep spaces)
space_replacement = "underscore"
```

With the above, a generated file will be:

- Directory: `/home/ben/Videos/Kodi/The Rookie/`
- Filename: `The_Rookie-S06E06-Secrets_and_Lies.mkv`

Directory components remain: `/home/ben/Videos/Kodi/The Rookie/`

---

## 5. Subtitle Matching & Junk Cleanup

### 5.1 Subtitle Association Logic

1. Extract language code suffix if present (e.g., `.en`, `.eng`, `.forced`, `.sdh`).
2. Map subtitle to target video file based on matching [Season, Episode] pairs in the same directory.
3. Rename subtitle file using the identical base string as the newly renamed video file while preserving the language code and original extension:

```
Video:    TV.SHOW.S01E01.1080p.mkv     → TV Show - S01E01 - Pilot.mkv
Subtitle: TV.SHOW.S01E01.1080p.en.srt  → TV Show - S01E01 - Pilot.en.srt
```

### 5.2 Junk Cleanup Options

When non-video clutter is found:

- **Option 1 (Purge):** Permanently unlinks/deletes `.nfo`, `.txt`, `.url`, and promo artwork.
- **Option 2 (Trash — Recommended):** Relocates all clutter files into a `.trash/` subfolder within the target directory.
- **Option 3 (Keep):** Leaves clutter files untouched.

---

## 6. Safety, Logs & Rollback

- **Default Dry-Run Mode:** Operations are strictly simulated unless explicitly confirmed via prompt or `--execute` flag.
- **Colour-Coded Preview:** Dry-run output uses colour to differentiate old names (dim/red) from proposed new names (green). Colour is auto-disabled when output is piped, when `--quiet` is set, when `--no-color` is passed, or when the `NO_COLOR` environment variable is set. Preview output is sorted by destination path, giving a natural season-then-episode ordering for easy review.
- **Conflict Prevention:** Preflight checks validate destination paths to ensure no existing file will be overwritten. Where a name collision is possible, the tool proposes a numbered alternative and flags it for user approval.
- **Cross-Platform Filename Rules:**
  - Normalize Unicode to NFC.
  - Enforce platform-specific constraints: trim to safe length (Windows path limit handling), disallow Windows reserved names (CON, PRN, AUX, NUL, COM1..COM9, LPT1..LPT9), and map illegal characters (`:`, `?`, `/`, `\\`, `*`, `<`, `>`, `|`) to `-` or spaces.
  - Normalize whitespace and collapse repeated separators. Provide optional strict mode for Windows-compatible filenames.
  - Optionally enforce a max filename length (configurable) and be mindful of full path length; when exceeding limits, apply deterministic shortening (hash suffix) to preserve uniqueness.
- **Cross-Filesystem Safety:** File operations attempt atomic `os.replace()`/`os.rename()` when source and destination are on the same filesystem. For cross-device moves, the tool falls back to copy-then-delete but records sufficient metadata to undo the operation if necessary.
- **Atomic Transactional Rename (Journaled):**
  1. Build a transaction plan (list of original → target paths) and run full preflight checks (conflicts, permissions, disk space).
  2. Write a transaction journal (JSON) to the target directory and fsync the file to disk before performing any changes. Journal includes operation IDs, timestamps, checksums, and a 'state' field.
  3. Execute renames using an atomic strategy:
     - For same-filesystem moves: use `os.link()` + `os.unlink()` which atomically fails if the destination already exists (TOCTOU-safe). Falls back to `os.replace()` for filesystems without hard link support.
     - For cross-filesystem operations: copy to a temporary staging file, then use `os.open(dst, O_CREAT|O_EXCL)` for exclusive creation at the destination before replacing with the staged copy. This prevents silent overwrites from concurrent processes.
     - Perform subtitle and sidecar renames in the same transaction.
  4. On any error, immediately stop and perform rollback using the journal (move any successful targets back to their originals). Journal state is updated and fsynced during rollback. Per-operation rollback failures are tracked individually — the journal gets state `"partially_rolled_back"` if any operation couldn't be reversed, with specific operations marked `"rollback_failed"`.
  5. On successful completion, mark the journal committed, fsync, and write a JSON undo history log.

  This guarantees either all planned renames applied or none (best-effort across filesystems). On restart, the tool detects an uncommitted journal and offers to resume or rollback automatically.
- **JSON Undo History Log:** Successful runs append a timestamped record (`renamed_history_YYYYMMDD_HHMMSS.json`) containing the final mapping. This file is written atomically and is usable by `--undo`.

```json
{
  "timestamp": "2026-07-27T13:19:00",
  "renamed_files": [
    {
      "original": "/media/downloads/TV.SHOW.S01E01.mkv",
      "new": "/media/downloads/TV Show - S01E01 - Pilot.mkv"
    }
  ]
}
```

- **Undo Support:** The `--undo <history_file>` flag reads a JSON history file and reverses all renames recorded in it, restoring files to their original names. Undo operations default to dry-run unless `--execute` is passed. Undo reads the journal format too and can attempt to repair interrupted transactions.
- **Logging & Observability:**
  - Structured JSON logs by default with configurable log levels (ERROR, WARN, INFO, DEBUG). Console output uses human-friendly formatting while file logs remain structured.
  - Logs are written to a per-run logfile in the target directory (rotated with size limits) or to a user-specified path.
  - Sensitive information (API keys, tokens) is redacted in logs. Network call timing, API responses (status codes), cache hits/misses, and transaction/journal events are logged at INFO/DEBUG.
  - `--verbose` / `--quiet` control verbosity; `--log-file` and `--log-level` allow explicit configuration.
- **Multipart & Multi-episode Handling:**
  - When a file contains multiple episodes (e.g., S01E01E02, S01E01-E02), the renamer produces a name reflecting the episode range: `Show - S01E01-E02 - Title.mkv` or `Show - S01E01,S01E02 - Title.mkv` based on the user's preferred separator.
  - For multi-part releases (e.g., CD1 / CD2 or Part1/Part2), preserve the part indicator in the output: `Show - S01E01 - Title (Part 1).mkv` and keep subtitle sidecars paired to the matching part when present.
  - When a single video file contains multiple episodes, subtitle matching will attempt to select a generic subtitle (no part suffix) or duplicate/rename subtitles per episode only when explicit per-episode subtitle files exist.
- **Crash Recovery:** On startup, detect any incomplete transaction journals in the target roots. Default behavior is to notify the user and offer to automatically complete the previous transaction, rollback, or leave it for manual inspection. In non-interactive mode, a warning is logged and the run proceeds.
- **Security & Privacy:**
  - Do not store API secrets in the journal or rename history. If a provider requires credentials, store them in system keyrings or user-specified credential files and never log raw values.
  - **Path Boundary Validation:** The `--undo` feature validates that all source and destination paths in a history file are within the scan root directory. Paths outside the root are rejected to prevent arbitrary file relocation via crafted history files.
  - **Symlink Rejection:** Cache files that are symlinks are refused on load to prevent cache poisoning attacks.
  - **ReDoS Protection:** User-supplied regex patterns from config are validated at parse time (must compile) and input length is capped (500 chars) when applying user patterns to prevent catastrophic backtracking.
  - **SPARQL Injection Prevention:** Show names are escaped (backslash, quotes, newlines, tabs) before interpolation into SPARQL queries.
  - **File Locking:** Cache writes use `fcntl.flock` (on supported platforms) to prevent corruption from concurrent tvrenamer instances.
  - **Structured Log Redaction:** Sensitive fields (api_key, token, password, secret) are automatically redacted in log output. The redaction filter does not mutate log records, allowing multiple handlers to process the same record safely.
  - **File Count Limit:** Directory scanning is capped at 100,000 files and skips symlinked directories to prevent resource exhaustion from recursive symlink loops.

- **Extensibility:** The transactional and logging primitives are provider-agnostic and can be reused for future provider integrations or bulk operations.

## Implementation Plan & Roadmap

High-level phases, deliverables, and validation steps to implement the features in this document:

1) Foundations
- Deliverables: src/sanitize.py (normalize_unicode, sanitize_name, shorten_path), unit tests tests/test_sanitize.py, platform examples (Windows, Unix).
- Validation: pytest unit coverage for normalization/sanitization; sample runs renaming test filenames.

2) Transactional Renamer Core
- Deliverables: src/renamer/transaction.py with build_transaction(), preflight_checks(), write_journal_atomically(), execute_transaction(), rollback_transaction(); journal schema spec; integration tests simulating crashes and cross-fs moves.
- Validation: Simulated mid-run failure tests, journal detection and automatic resume/rollback behavior.

3) Caching & Backoff
- Deliverables: src/cache.py implementing JSON disk cache with TTL, LRU cap, file locking, stale-while-revalidate; provider rate-limiter with exponential backoff, jitter, and circuit-breaker.
- Validation: Mock provider tests validating retries, cache hits/misses, and offline-mode behavior.

4) Multipart & Subtitle Pairing
- Deliverables: src/episodes/multipart.py implementing multi-episode naming, part-preservation, subtitle pairing rules and tests.
- Validation: Unit tests for multi-episode filenames and subtitle sidecar behavior.

5) Logging, CLI & UX
- Deliverables: Structured JSON logs, per-run logfile rotation, per-provider log sampling and redaction rules, request/response size truncation, request timing metrics, and configurable log-levels. Console output remains human-friendly (colour, compact summaries) while file logs are structured JSON for ingestion.
- CLI Deliverables: CLI options (--log-file, --log-level, --resume/--rollback, --undo, --interactive) with improved interactive wizard flows (filtering, batch confirmation, progress bars), non-interactive scripting mode, and clear exit codes for automation.
- Run Scripts & Packaging: Provide robust run scripts (e.g., `run.sh`) that detect/create virtualenvs, ensure editable installs during development, reinstall stale entrypoints, and forward args to the installed console script. Packaging deliverables include a `pyproject.toml`/`setup.cfg` for building sdist/wheel, a console entrypoint (`tvrenamer`), CI job to build/test/package, and guidance for installation via pip/pipx and platform-specific installers.
- Validation: Manual and automated checks that logs redact secrets and include transaction/cache/provider events; integration tests exercising interactive and non-interactive flows (expect/pexpect or equivalent); packaging smoke tests (install in ephemeral venv, run `tvrenamer --help`), and CI steps to publish to TestPyPI on tagged releases.

6) Safety & Recovery Polish
- Deliverables: Startup detection of uncommitted journals, --resume/--rollback behavior, sample undo command and docs updates.
- Validation: End-to-end dry-run and execute runs, recovery from interrupted transaction, undo tests.

## Task Breakdown (suggested todos and subtasks)

- Foundations
  - sanitize-naming: Implement cross-platform sanitization helpers and tests.
  - sanitize-windows: Add Windows-specific reserved name handling and path-length tests.

- Transactional Renamer
  - transactional-core: Implement transaction planner, atomic move primitives, and journal schema.
  - transactional-tests: Integration tests for partial failure, cross-fs, and crash recovery.

- Caching & Backoff
  - cache-core: Implement disk cache (atomic writes, TTL, LRU) and file locking.
  - rate-limiter: Implement per-provider limiter, backoff+jitter, and circuit-breaker.

- Multipart & Subtitles
  - multipart-detection: Implement multi-episode and multi-part filename parsing.
  - subtitle-pairing: Implement reliable subtitle association and testing.

- Logging & CLI
  - logging-core: Structured logging, log rotation, redact rules.
  - cli-flags: Add --log-file, --log-level, --resume, --rollback, --undo options to CLI.

- Tests, CI & Packaging
  - tests-ci: Add pytest config and GitHub Actions workflow to run unit + integration tests.
  - packaging: Create requirements.txt / setup.cfg / entrypoint for CLI.

Additions to design.md will be kept synchronized with implementation and each completed todo should update the design doc with specific implementation notes and test outcomes.
