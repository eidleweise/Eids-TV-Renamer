# Requirements Document

## Introduction

This document specifies the requirements for completing all partially implemented features described in the tvrenamer design document (design.md). The existing codebase implements core renaming, caching, provider chaining, and journaled transactions, but 17 feature areas remain incomplete or missing. This specification covers: path-aware extraction improvements, show name cleaning enhancements, formatting token aliases, exit codes, conflict reporting, colour-coded preview, junk cleanup, undo support, JSON history logging, exclude patterns, fetch-titles flags, verbose/quiet modes, prefetch seasons, offline mode, cache integrity, crash recovery prompts, and cross-platform strict mode activation.

## Glossary

- **Engine**: The rename planning module (`tvrenamer/renamer/engine.py`) that scans directories, extracts metadata, and produces rename plans
- **CLI**: The command-line interface module (`tvrenamer/cli.py`) that parses arguments and orchestrates execution
- **Config_Loader**: The TOML configuration loading module (`tvrenamer/config.py`)
- **Cache**: The disk-based JSON cache module (`tvrenamer/cache.py`) providing TTL, LRU eviction, and atomic writes
- **Sanitizer**: The filename sanitization module (`tvrenamer/sanitize.py`)
- **Transaction_Manager**: The journaled atomic rename module (`tvrenamer/renamer/transaction.py`)
- **Provider_Chain**: The ordered metadata provider lookup module (`tvrenamer/providers/chain.py`)
- **TVMaze_Provider**: The TVMaze API metadata provider (`tvrenamer/providers/tvmaze.py`)
- **Circuit_Breaker**: The failure-counting mechanism that opens after N consecutive failures to prevent repeated failing calls
- **Directory_Blacklist**: A configurable list of generic folder names that should not be used as show name sources
- **Scene_Tags**: Release group quality/codec/source identifiers embedded in filenames (e.g., PROPER, 720p, x264)
- **History_File**: A timestamped JSON file recording all rename operations from a successful run
- **Junk_File**: A file whose extension matches the configurable junk extensions list and is located within the scanned media directory

## Requirements

### Requirement 1: Grandparent Directory Show Name Extraction

**User Story:** As a user with media organized in `Show/Season X/file.mkv` structures, I want the tool to extract the show name from the grandparent directory when the parent is a Season folder, so that season-only folders do not become the show name.

#### Acceptance Criteria

1. WHEN the parent directory name matches a season pattern (case-insensitive match against "Season N", "season N", "Season_N", "S01", "s01", "season.N", where N is 1–2 digits with optional leading zero), THE Engine SHALL extract the show name from the grandparent directory instead of the parent directory.
2. IF the parent directory is a season folder and the grandparent directory name matches a blacklisted name (one of: "Downloads", "TV Shows", "TV", "Completed", "Desktop", "Videos", "Media"), THEN THE Engine SHALL fall back to extracting the show name from the filename using the existing pattern extraction logic.
3. WHEN the parent directory is a season folder and the grandparent directory is not a blacklisted name, THE Engine SHALL apply the existing show name cleaning rules to the grandparent directory name and use the result as the show name.
4. WHEN the parent directory does not match a season pattern, THE Engine SHALL extract the show name from the parent directory as the current default behaviour.
5. IF the parent directory is a season folder and no grandparent directory exists (file depth is fewer than 2 levels from the scan root), THEN THE Engine SHALL fall back to extracting the show name from the filename using the existing pattern extraction logic.

### Requirement 2: Directory Blacklist Guard

**User Story:** As a user whose media may reside in generic folders like "Downloads" or "TV Shows", I want the tool to ignore generic directory names when extracting show names, so that meaningless folder names are not used as show names.

#### Acceptance Criteria

1. THE Config_Loader SHALL support a `[path_extraction]` section with a `directory_blacklist` list of folder names to ignore during show name extraction.
2. WHEN a user-defined `directory_blacklist` is present in the configuration, THE Engine SHALL merge those entries with the default blacklist so that both sets of names are ignored.
3. THE Engine SHALL provide a default blacklist containing: "Downloads", "TV Shows", "TV", "Completed", "Desktop", "Videos", "Media", "Series", "Shows".
4. WHEN a candidate directory name (the immediate parent or any ancestor up to a maximum of 5 levels above the file) matches a blacklisted entry by exact full-name case-insensitive comparison, THE Engine SHALL skip that directory and evaluate the next ancestor directory.
5. IF no non-blacklisted directory is found within 5 ancestor levels of the file, THEN THE Engine SHALL fall back to using "Unknown" as the show name.
6. IF the `[path_extraction]` section is absent or the `directory_blacklist` key is not defined, THEN THE Engine SHALL use only the default blacklist without error.

### Requirement 3: Configurable Scene Tag Stripping

**User Story:** As a user with scene-released media files, I want known scene tags to be stripped from filenames during show name cleaning, so that quality and codec markers do not pollute show names or API queries.

#### Acceptance Criteria

1. THE Config_Loader SHALL support a `[scene_tags]` section containing a `strip` key whose value is a list of tag strings (maximum 100 entries, each entry between 1 and 30 characters) and a `group_tag_patterns` key whose value is a list of regex pattern strings (maximum 20 entries, each entry between 1 and 200 characters).
2. WHEN a scene tag from the configured `strip` list appears in a filename after separator normalization (dots, underscores, and hyphens replaced with spaces), THE Engine SHALL remove the tag using case-insensitive matching bounded by whitespace or string start/end, and collapse any resulting consecutive whitespace into a single space.
3. THE Config_Loader SHALL support a `group_tag_patterns` list of regex patterns for release group identifiers.
4. WHEN a filename matches a `group_tag_patterns` regex pattern after separator normalization, THE Engine SHALL remove the matched portion and trim any leading or trailing whitespace from the resulting show name.
5. THE Engine SHALL apply the following default values when no `[scene_tags]` section is present in the loaded configuration: `strip` defaults to ["PROPER", "REPACK", "RERIP", "INTERNAL", "WEB-DL", "WEBRip", "HDTV", "BluRay", "BDRip", "x264", "x265", "H.264", "H.265", "HEVC", "AAC", "DTS", "720p", "1080p", "2160p", "4K"] and `group_tag_patterns` defaults to ["\\[.*?\\]", "-\\w+$"].
6. IF the `[scene_tags]` section is present but the `strip` list is empty, THEN THE Engine SHALL skip scene tag stripping and proceed to group tag removal without error.
7. THE Engine SHALL apply scene tag stripping after separator normalization and before group tag removal, such that the cleaning order is: separator normalization → scene tag removal → group tag removal → title casing.

### Requirement 4: Year Extraction and Preservation

**User Story:** As a user with shows that share names but differ by year (e.g., "Battlestar Galactica 2003" vs the original), I want the tool to detect and preserve year tokens for API disambiguation and optional use in the output template.

#### Acceptance Criteria

1. WHEN a four-digit number in the range 1950–2099 appears in the filename or immediate parent directory name, positioned after the show name text and before or without any SxxExx or season/episode marker, THE Engine SHALL extract that number as the year and store it separately from the cleaned show name.
2. IF a four-digit number in the range 1950–2099 appears after a season/episode marker (e.g., as part of an episode title or release year tag like "2003" following "S01E01"), THEN THE Engine SHALL NOT treat it as the show year.
3. THE Engine SHALL pass the extracted year to the provider chain's show search query so providers can disambiguate between shows with identical names.
4. WHEN the template contains a `{year}` or `{y}` token and a year was extracted, THE Engine SHALL substitute the four-digit year value into that token position in the output filename.
5. WHEN the template contains a `{year}` or `{y}` token and no year was detected from the filename or directory name, THE Engine SHALL substitute an empty string for that token, removing it and any immediately preceding single space or hyphen-with-surrounding-spaces (` - ` or ` `) that would leave a double separator or trailing punctuation in the output filename.

### Requirement 5: Title-Cased Show Names

**User Story:** As a user, I want cleaned show names to be title-cased, so that output filenames look professional and consistent regardless of the original filename casing.

#### Acceptance Criteria

1. WHEN separator normalization, scene tag removal, and group tag removal are complete, THE Engine SHALL capitalize the first letter of each word in the cleaned show name.
2. THE Engine SHALL keep the following short words in lowercase when they are not the first word of the show name: "a", "an", "the", "and", "but", "or", "nor", "for", "yet", "so", "in", "on", "at", "to", "by", "of", "up", "is".
3. THE Engine SHALL always capitalize the first word of the cleaned show name regardless of whether it appears in the lowercase short-word list.
4. IF a word in the source show name is fully uppercase and 2–5 characters long (e.g., "CSI", "FBI", "NCIS"), THEN THE Engine SHALL preserve that word in uppercase without applying title-case transformation to it.

### Requirement 6: Short Formatting Token Aliases

**User Story:** As a user who prefers shorter templates, I want to use `{s}`, `{e}`, `{t}`, and `{y}` as aliases for `{season}`, `{episode}`, `{title}`, and `{year}`, so that templates are more concise.

#### Acceptance Criteria

1. WHEN the template contains `{s}`, THE Engine SHALL substitute the two-digit zero-padded season number, identical to the value produced by `{season}`.
2. WHEN the template contains `{e}`, THE Engine SHALL substitute the two-digit zero-padded episode number, identical to the value produced by `{episode}`.
3. WHEN the template contains `{t}`, THE Engine SHALL substitute the episode title string, identical to the value produced by `{title}`.
4. WHEN the template contains `{y}`, THE Engine SHALL substitute the four-digit premiere year string, identical to the value produced by `{year}`.
5. WHEN the template contains both a short alias and its corresponding long-form token (e.g., `{s}` and `{season}`), THE Engine SHALL substitute both with the same value, producing identical output for each occurrence.
6. THE Engine SHALL treat token aliases as case-sensitive, recognizing only the lowercase forms `{s}`, `{e}`, `{t}`, and `{y}`.
7. IF the underlying metadata for an alias token is unavailable (e.g., no premiere year found for `{y}`), THEN THE Engine SHALL substitute an empty string for that alias, matching the fallback behavior of the corresponding long-form token.

### Requirement 7: Structured Exit Codes

**User Story:** As an automation user running tvrenamer in scripts and cron jobs, I want the CLI to return specific exit codes for different failure modes, so that I can handle errors programmatically.

#### Acceptance Criteria

1. WHEN all operations complete successfully (including dry-run with at least one media file found), THE CLI SHALL exit with code 0.
2. WHEN no media files (video or subtitle files as defined by supported extensions) are found in the target directory or its subdirectories, THE CLI SHALL exit with code 1.
3. IF API errors prevent metadata lookup for one or more files during the run, THEN THE CLI SHALL exit with code 2, regardless of whether other files were processed successfully.
4. IF file operation errors occur (permission denied, disk full, or rename failure) during execution, THEN THE CLI SHALL exit with code 3, regardless of whether other files were renamed successfully.
5. IF invalid arguments or unreadable configuration are provided, THEN THE CLI SHALL exit with code 4 before performing any file scanning or API operations.
6. IF multiple error categories occur in a single run, THEN THE CLI SHALL exit with the highest-priority exit code, where priority is determined by lowest non-zero code value (code 1 > code 2 > code 3 in priority).
7. WHEN the CLI exits with a non-zero code, THE CLI SHALL write a one-line summary of the failure reason to stderr before terminating.

### Requirement 8: Conflict Prevention Reporting

**User Story:** As a user reviewing a dry-run preview, I want to see which files had naming conflicts that required a counter suffix, so that I am aware of potential issues before execution.

#### Acceptance Criteria

1. WHEN a rename plan entry requires a counter suffix to avoid a filename collision, THE Engine SHALL include a conflict flag and the originally-intended destination path (before the suffix was added) in the plan entry metadata for that file.
2. WHEN operating in dry-run mode and the plan contains one or more conflict-flagged entries, THE CLI SHALL prefix each conflict-flagged line with a "[CONFLICT]" label in the dry-run output.
3. IF the `--verbose` flag is set and the plan contains one or more conflict-flagged entries, THEN THE CLI SHALL display the total count of conflicts as a summary line after the per-entry listing.
4. WHEN operating in execute mode and the plan contains one or more conflict-flagged entries, THE CLI SHALL display the conflict-flagged entries with the "[CONFLICT]" prefix before performing renames, unless the `--quiet` flag is set.

### Requirement 9: Colour-Coded Dry-Run Preview

**User Story:** As a user reviewing proposed renames in a terminal, I want old filenames displayed in dim/red and new filenames displayed in green, so that I can visually distinguish current state from proposed state at a glance.

#### Acceptance Criteria

1. WHEN displaying a dry-run preview to a TTY-attached terminal, THE CLI SHALL render each rename as a single line showing the old filename in dim ANSI style (SGR code 2) followed by an arrow separator and the proposed new filename in green ANSI style (SGR code 32).
2. WHEN displaying a dry-run preview to a TTY-attached terminal, THE CLI SHALL render proposed new filenames in green ANSI colour (SGR code 32).
3. IF stdout is not attached to a TTY (e.g., piped or redirected), THEN THE CLI SHALL emit preview lines containing zero ANSI escape sequences.
4. IF the `--quiet` flag is active, THEN THE CLI SHALL suppress all preview output entirely, producing no dry-run lines to stdout.
5. IF the `--no-color` flag is provided, THEN THE CLI SHALL emit preview lines containing zero ANSI escape sequences regardless of TTY detection.
6. IF the environment variable `NO_COLOR` is set to a non-empty value, THEN THE CLI SHALL emit preview lines containing zero ANSI escape sequences, consistent with the no-color.org convention.

### Requirement 10: Junk File Cleanup

**User Story:** As a user with media folders cluttered by .nfo, .txt, .url, and artwork files, I want the tool to classify and optionally remove or trash junk files, so that my media directories stay clean.

#### Acceptance Criteria

1. THE CLI SHALL support a `--clean-junk` flag that permanently deletes files classified as Junk.
2. THE CLI SHALL support a `--trash-junk` flag that moves files classified as Junk into a `.trash/` subdirectory located within the same parent directory as the junk file, creating the `.trash/` subdirectory if it does not already exist.
3. THE Config_Loader SHALL support a `[junk]` section with an `extensions` list defining which file extensions are considered junk; IF the `[junk]` section is absent or the `extensions` list is empty, THEN THE Config_Loader SHALL use the default extensions: `.nfo`, `.txt`, `.url`, `.jpg`, `.jpeg`, `.png`, `.bmp`, `.tbn`.
4. THE Engine SHALL classify each scanned file into exactly one category based on its extension compared case-insensitively: Video (matching video extensions), Subtitle (matching subtitle extensions), Junk (matching the configured junk extensions list), or Unknown (matching none of the above).
5. WHEN `--clean-junk` is active, THE CLI SHALL delete only files classified as Junk and SHALL not modify, move, or delete files classified as Video, Subtitle, or Unknown.
6. WHEN `--trash-junk` is active, THE CLI SHALL move only files classified as Junk into the `.trash/` subdirectory, preserving the original filename.
7. WHEN neither `--clean-junk` nor `--trash-junk` is provided, THE Engine SHALL leave junk files untouched in their original location.
8. IF a junk file cannot be deleted or moved due to a filesystem error, THEN THE CLI SHALL log a warning that includes the file path and error reason, and SHALL continue processing the remaining files without aborting.
9. IF both `--clean-junk` and `--trash-junk` are provided simultaneously, THEN THE CLI SHALL reject the command with an error message indicating the two flags are mutually exclusive, and SHALL not process any files.

### Requirement 11: Undo Flag

**User Story:** As a user who wants to reverse a previous rename operation, I want an `--undo` flag that reads a JSON history file and restores files to their original names, so that mistakes are easily reversible.

#### Acceptance Criteria

1. THE CLI SHALL support an `--undo <history_file>` argument that accepts a path to a JSON history file.
2. WHEN `--undo` is provided without `--execute`, THE CLI SHALL display a dry-run preview listing each reversal operation as a line showing the current path and the original path it would be restored to.
3. WHEN `--undo` is provided with `--execute`, THE CLI SHALL perform the reversal operations using the same journaled transaction mechanism, rolling back all completed reversals if any single operation fails.
4. IF a source file in the undo plan no longer exists at the recorded "new" path, THEN THE CLI SHALL log a warning identifying the missing file path and skip that entry without aborting the remaining operations.
5. IF the original path already contains a file, THEN THE CLI SHALL rename the file using a counter suffix appended before the extension (e.g., `filename_1.mkv`, `filename_2.mkv`) and log a warning identifying the conflict and the suffix-adjusted destination.
6. IF the history file path does not exist or is not readable, THEN THE CLI SHALL exit with exit code 4 and display an error message indicating the file could not be found or read.
7. IF the history file contains invalid JSON or does not contain a top-level `renamed_files` array with objects having `original` and `new` string fields, THEN THE CLI SHALL exit with exit code 4 and display an error message indicating the file format is invalid.

### Requirement 12: JSON Undo History Log

**User Story:** As a user, I want each successful rename run to produce a timestamped JSON history file, so that I have a persistent record of all operations that can be used for undo.

#### Acceptance Criteria

1. WHEN a transaction commits successfully and the `renamed_files` array contains at least one entry, THE Transaction_Manager SHALL write a UTF-8 encoded history file named `renamed_history_YYYYMMDD_HHMMSS.json` (using local-time wall clock) to the target directory.
2. THE history file SHALL contain a JSON object with fields: `timestamp` (ISO 8601 string with timezone offset), `run_id` (UUID v4 string matching the transaction's correlation identifier), and `renamed_files` (array of `{original, new}` objects where `original` and `new` are absolute path strings).
3. THE Transaction_Manager SHALL write the history file atomically (write-to-temp then rename) so that a concurrent reader never observes a partially written file.
4. THE history file format SHALL be compatible with the `--undo` flag input format such that passing the file path to `--undo --execute` reverses every rename recorded in the `renamed_files` array.
5. IF the transaction commits successfully but the history file write fails (e.g., permission denied, disk full), THEN THE Transaction_Manager SHALL log an error indicating the history write failure and the associated `run_id`, and SHALL NOT roll back the already-committed renames.
6. IF the transaction commits successfully but the `renamed_files` array is empty (no files were renamed), THEN THE Transaction_Manager SHALL NOT write a history file.

### Requirement 13: Exclude Flag

**User Story:** As a user with sample files or extras mixed in with episodes, I want to exclude files matching glob patterns from processing, so that non-episode files are not renamed.

#### Acceptance Criteria

1. THE CLI SHALL support an `--exclude <pattern>` argument accepting a glob pattern string.
2. THE CLI SHALL allow multiple `--exclude` arguments to specify multiple patterns.
3. WHEN a file path matches any exclude pattern, THE Engine SHALL skip that file and not include it in the rename plan, where the glob pattern is matched against the file's path relative to the scan root directory.
4. THE Config_Loader SHALL support an `exclude_patterns` list in the `[defaults]` section for persistent exclusion rules.
5. THE Engine SHALL apply both CLI-provided and config-provided exclude patterns as a union, skipping any file whose relative path matches at least one pattern from either source.
6. IF an exclude pattern is syntactically invalid, THEN THE CLI SHALL report an error message indicating the invalid pattern and exit without processing any files.
7. WHEN the Engine skips a file due to an exclude pattern match, THE Engine SHALL log the skipped file path at DEBUG level.

### Requirement 14: Fetch-Titles and No-Fetch-Titles Flags

**User Story:** As a user who sometimes wants to rename files without network access, I want explicit `--fetch-titles` and `--no-fetch-titles` flags, so that I can control whether the tool queries metadata providers.

#### Acceptance Criteria

1. THE CLI SHALL support a `--fetch-titles` / `-f` flag that explicitly enables metadata provider queries.
2. THE CLI SHALL support a `--no-fetch-titles` flag that disables all metadata provider queries for the run.
3. IF both `--fetch-titles` and `--no-fetch-titles` are supplied in the same invocation, THEN THE CLI SHALL reject the command with an error message indicating the flags are mutually exclusive, and exit without processing any files.
4. WHEN `--no-fetch-titles` is active, THE Engine SHALL skip all provider lookups and resolve the `{title}` token to an empty string, removing any surrounding template delimiters that would leave leading or trailing separators in the resulting filename.
5. THE Config_Loader SHALL support a `fetch_titles` boolean in the `[defaults]` section, defaulting to `true` when the key is absent from the configuration file.
6. CLI flags SHALL take precedence over config file values for `fetch_titles`; WHEN neither a CLI flag nor a config value is provided, THE system SHALL default to enabling metadata provider queries.

### Requirement 15: Verbose and Quiet Flags

**User Story:** As a user running tvrenamer in scripts or debugging issues, I want `--verbose` and `--quiet` flags to control console output verbosity, so that I see the right level of detail for my context.

#### Acceptance Criteria

1. THE CLI SHALL support a `--verbose` / `-v` flag that enables detailed console output including provider query URLs, API response statuses, match reasoning, cache hit/miss information, and template token resolution details.
2. THE CLI SHALL support a `--quiet` / `-q` flag that suppresses all console output except error messages and explicit warnings that indicate data loss or skipped files.
3. WHILE `--verbose` is active, THE CLI SHALL print provider query URLs, response statuses, cache hit/miss indicators, and template token resolution details to stderr.
4. WHILE `--quiet` is active, THE CLI SHALL suppress dry-run previews, progress indicators, informational messages, and success confirmations, emitting only error messages and data-loss warnings to stderr.
5. IF both `--verbose` and `--quiet` are provided, THEN THE CLI SHALL report an error indicating the flags are mutually exclusive and exit with code 4 (invalid arguments).
6. WHEN neither `--verbose` nor `--quiet` is provided, THE CLI SHALL output dry-run previews, rename summaries, and error messages to stderr, without printing API response details or cache diagnostics.

### Requirement 16: Prefetch Seasons

**User Story:** As a user processing many episodes of the same show, I want the TVMaze provider to prefetch all episode data for a season on first access, so that subsequent lookups are served from cache without additional API calls.

#### Acceptance Criteria

1. THE Config_Loader SHALL support a `prefetch_seasons` boolean flag under `[provider.tvmaze]` that defaults to false when not specified.
2. WHEN `prefetch_seasons` is true and the TVMaze_Provider performs an episode title lookup for a show-and-season combination not yet prefetched in the current run, THE TVMaze_Provider SHALL fetch the full episode listing for that season number and store each episode in the cache using the same key format as individual episode lookups.
3. WHEN prefetched data is available in the cache for a requested show, season, and episode number, THE TVMaze_Provider SHALL return the episode title from cache without making any additional API calls to TVMaze.
4. THE TVMaze_Provider SHALL acquire rate-limiter tokens before each prefetch API request, blocking until a token is available rather than bypassing the limiter.
5. IF a prefetch request fails or returns incomplete data, THEN THE TVMaze_Provider SHALL fall back to individual per-episode API lookups for any episodes not successfully cached during prefetch.

### Requirement 17: Offline Mode

**User Story:** As a user on an unreliable network, I want the tool to automatically switch to offline mode after repeated provider failures, so that it completes the run using cached data rather than hanging or failing on every file.

#### Acceptance Criteria

1. WHEN the Circuit_Breaker opens (5 consecutive provider failures reached, the default threshold), THE Provider_Chain SHALL enter offline mode for the remainder of the current run.
2. WHILE in offline mode, THE Provider_Chain SHALL skip all network calls to all providers and serve only cached results from the disk cache.
3. WHILE in offline mode and no cached result exists for a requested show/season/episode, THE Provider_Chain SHALL return an empty string for the title token (graceful degradation).
4. WHEN the `--verbose` flag is active and offline mode activates, THE CLI SHALL print a warning message to stderr: "WARNING: Offline mode activated — serving cached results only".
5. THE Provider_Chain SHALL NOT exit offline mode during the same run, even if the circuit-breaker recovery time elapses; offline mode persists until the process terminates.

### Requirement 18: Cache Version, Migration, and Integrity

**User Story:** As a user whose cache file may become stale or corrupted across tool upgrades, I want the cache to include a version field and integrity checks, so that incompatible or corrupt cache files are detected and handled gracefully.

#### Acceptance Criteria

1. THE Cache SHALL include a `_meta` entry in the persisted JSON containing a `version` integer field (starting at 1) and a `checksum` string field holding a SHA-256 hex digest.
2. WHEN the cache file is loaded and the `version` field is missing or lower than the current expected version, THE Cache SHALL discard all cached data entries and start with an empty cache while preserving the new version number in the `_meta` entry.
3. WHEN the cache file is loaded and the `checksum` does not match the SHA-256 hex digest computed over the data payload, THE Cache SHALL rename the corrupt file to `.tvrenamer_cache.json.corrupt.{epoch_seconds}` and start with an empty cache.
4. THE Cache SHALL compute the checksum by serializing the data payload (all entries excluding the `_meta` entry) as JSON with keys sorted lexicographically, then computing the SHA-256 hex digest of the resulting UTF-8 byte string before writing.
5. IF the corrupt file rotation rename fails due to filesystem errors, THEN THE Cache SHALL log a warning and proceed with an empty in-memory cache without persisting the corrupt file under a new name.

### Requirement 19: Crash Recovery Prompt

**User Story:** As a user whose previous run may have been interrupted, I want the tool to detect uncommitted journals on startup and offer to resume or rollback, so that I do not have incomplete renames lingering.

#### Acceptance Criteria

1. WHEN the CLI starts (outside of explicit `--resume` or `--rollback` mode) and one or more transaction journal files with state "pending" are detected in the target directory, THE CLI SHALL notify the user by displaying the number of pending journals and the file path of each.
2. WHEN in interactive mode and pending journals are detected, THE CLI SHALL prompt the user to choose one of: resume, rollback, or ignore, and SHALL wait for a valid selection before proceeding.
3. IF the user chooses "ignore" in the interactive prompt, THEN THE CLI SHALL leave the pending journal files unchanged on disk and proceed with the current run without executing or rolling back any journal operations.
4. WHEN in non-interactive mode and pending journals are detected, THE CLI SHALL log a warning message indicating the count of pending journals and suggest using `--resume` or `--rollback`, and SHALL proceed with the current run without modifying the journals.
5. IF the user chooses "resume", THEN THE CLI SHALL execute each pending journal transaction in chronological order (oldest first) before proceeding with the current run.
6. IF the user chooses "rollback", THEN THE CLI SHALL rollback each pending journal transaction in reverse chronological order (newest first) before proceeding with the current run.
7. IF a resume or rollback operation fails for a journal, THEN THE CLI SHALL log an error message indicating which journal failed and the reason, skip the failed journal, and continue processing any remaining pending journals.
8. WHEN the CLI starts and no transaction journal files with state "pending" exist in the target directory, THE CLI SHALL proceed with normal operation without displaying any recovery prompt or warning.

### Requirement 20: Cross-Platform Strict Mode Activation

**User Story:** As a user generating files destined for a Windows filesystem (e.g., NAS or external drive), I want to enable strict Windows filename sanitization from the CLI or config, so that generated filenames are compatible with Windows without manual editing.

#### Acceptance Criteria

1. THE CLI SHALL support a `--strict-windows` flag that activates Windows-compatible filename sanitization.
2. THE Config_Loader SHALL support a `strict_windows` boolean in the `[defaults]` section.
3. WHEN strict Windows mode is active, THE Sanitizer SHALL avoid Windows reserved names (CON, PRN, AUX, NUL, COM1–COM9, LPT1–LPT9) by appending a deterministic hash suffix, and SHALL trim trailing dots and spaces from filenames.
4. WHEN strict Windows mode is not active, THE Sanitizer SHALL apply only the platform-native sanitization rules (current default behaviour on the host OS).
5. CLI `--strict-windows` flag SHALL take precedence over the config file value; WHEN neither the CLI flag nor the config value is set, THE Sanitizer SHALL default to non-strict mode.
