# Implementation Plan: Design Gap Completion

## Overview

This plan implements the 20 requirements that fill the gaps between the tvrenamer design document and the actual codebase. Changes are organized by module, with engine extraction/cleaning logic first, then provider and cache upgrades, followed by CLI flag wiring and integration. All code is Python, targeting the existing project structure.

## Tasks

- [ ] 1. Add exception types and config parsing extensions
  - [ ] 1.1 Create custom exception classes in a new `tvrenamer/exceptions.py` module
    - Define `TVRenamerError`, `NoMediaFoundError`, `ProviderError`, `FileOperationError`, `InvalidConfigError`
    - Each exception maps to an exit code as specified in the design
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5_

  - [ ] 1.2 Extend `tvrenamer/config.py` to parse new TOML sections
    - Add parsing for `[path_extraction]` with `directory_blacklist` list
    - Add parsing for `[scene_tags]` with `strip` list and `group_tag_patterns` list (with length/size validation)
    - Add parsing for `[junk]` with `extensions` list
    - Add parsing for `[defaults]` keys: `fetch_titles`, `strict_windows`, `exclude_patterns`, `space_replacement`
    - Add parsing for `[provider.tvmaze]` with `prefetch_seasons` boolean
    - Return defaults when sections are absent
    - _Requirements: 2.1, 2.6, 3.1, 3.5, 3.6, 10.3, 13.4, 14.5, 16.1, 20.2_

  - [ ]* 1.3 Write unit tests for config parsing extensions
    - Test each new section with present/absent/empty values
    - Test validation constraints (max entries, character limits for scene_tags)
    - _Requirements: 2.1, 2.6, 3.1, 3.5, 3.6, 10.3, 13.4, 14.5, 16.1, 20.2_

- [ ] 2. Implement engine extraction and cleaning helpers
  - [ ] 2.1 Implement `_is_season_dir(name)` in `tvrenamer/renamer/engine.py`
    - Match patterns: "Season N", "season N", "Season_N", "S01", "s01", "season.N" (case-insensitive, 1-2 digits with optional leading zero)
    - Return the season number as int or None
    - _Requirements: 1.1_

  - [ ] 2.2 Implement `_resolve_show_name(filepath, root, config)` in `tvrenamer/renamer/engine.py`
    - Walk ancestors up to 5 levels, apply grandparent logic when parent is a season dir
    - Merge default blacklist with user-provided blacklist (case-insensitive matching)
    - Fall back to filename extraction when all ancestors are blacklisted, or return "Unknown" if no extraction possible
    - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 2.2, 2.3, 2.4, 2.5, 2.6_

  - [ ]* 2.3 Write property test for show name resolution
    - **Property 1: Show Name Resolution from Ancestors**
    - **Validates: Requirements 1.1, 1.2, 1.3, 1.4, 1.5, 2.4, 2.5**

  - [ ]* 2.4 Write property test for blacklist merge
    - **Property 2: Blacklist Merge is a Superset**
    - **Validates: Requirements 2.2, 2.4**

  - [ ] 2.5 Implement `_strip_scene_tags(name, config)` in `tvrenamer/renamer/engine.py`
    - Apply separator normalization (dots, underscores, hyphens → spaces)
    - Remove configured scene tags using case-insensitive word-boundary matching
    - Remove group tag patterns via regex
    - Collapse resulting whitespace
    - Apply cleaning order: separator normalization → scene tag removal → group tag removal → title casing
    - _Requirements: 3.2, 3.4, 3.5, 3.6, 3.7_

  - [ ]* 2.6 Write property test for scene tag removal
    - **Property 3: Scene Tag and Group Tag Removal**
    - **Validates: Requirements 3.2, 3.4, 3.7**

  - [ ] 2.7 Implement `_extract_year(name)` in `tvrenamer/renamer/engine.py`
    - Detect 4-digit numbers in range 1950–2099 positioned before any SxxExx marker
    - Do NOT treat numbers after season/episode markers as the year
    - Return tuple of (cleaned_name_without_year, year_int_or_None)
    - _Requirements: 4.1, 4.2_

  - [ ]* 2.8 Write property test for year extraction positioning
    - **Property 4: Year Extraction Positioning**
    - **Validates: Requirements 4.1, 4.2**

  - [ ] 2.9 Implement `_title_case(name)` in `tvrenamer/renamer/engine.py`
    - Capitalize first letter of each word
    - Keep short words lowercase when not first word: "a", "an", "the", "and", "but", "or", "nor", "for", "yet", "so", "in", "on", "at", "to", "by", "of", "up", "is"
    - Preserve 2–5 character fully uppercase words (acronyms like "CSI", "FBI")
    - Always capitalize the first word
    - _Requirements: 5.1, 5.2, 5.3, 5.4_

  - [ ]* 2.10 Write property test for title casing rules
    - **Property 5: Title Casing Rules**
    - **Validates: Requirements 5.1, 5.2, 5.3, 5.4**

  - [ ] 2.11 Implement `_expand_template(template, tokens)` in `tvrenamer/renamer/engine.py`
    - Support short aliases: `{s}` → season, `{e}` → episode, `{t}` → title, `{y}` → year
    - Case-sensitive matching (lowercase only)
    - Handle missing metadata by substituting empty string and cleaning adjacent separators
    - _Requirements: 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7, 4.4, 4.5_

  - [ ]* 2.12 Write property test for short token alias equivalence
    - **Property 6: Short Token Aliases Equivalence**
    - **Validates: Requirements 6.1, 6.2, 6.3, 6.4, 6.5, 6.6, 6.7**

- [ ] 3. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 4. Implement file classification and exclude patterns in engine
  - [ ] 4.1 Implement `_classify_file(ext, junk_exts)` in `tvrenamer/renamer/engine.py`
    - Classify by extension (case-insensitive): video, subtitle, junk, or unknown
    - Use existing VIDEO_EXTS, subtitle ext set, and configurable junk extensions
    - _Requirements: 10.4_

  - [ ]* 4.2 Write property test for file classification
    - **Property 7: File Classification Determinism and Correctness**
    - **Validates: Requirements 10.4**

  - [ ] 4.3 Implement `_matches_exclude(relpath, patterns)` in `tvrenamer/renamer/engine.py`
    - Use `fnmatch` or `pathlib.PurePath.match` for glob pattern matching against relative path
    - Return True if any pattern matches
    - Log skipped files at DEBUG level
    - _Requirements: 13.3, 13.5, 13.7_

  - [ ]* 4.4 Write property test for exclude patterns
    - **Property 8: Exclude Patterns Filter Completeness**
    - **Validates: Requirements 13.3, 13.5**

  - [ ] 4.5 Refactor `plan_renames()` to integrate new helpers
    - Replace `_clean_show_name` calls with pipeline: `_resolve_show_name` → `_strip_scene_tags` → `_extract_year` → `_title_case`
    - Use `_expand_template` instead of direct `.format()` for template resolution
    - Add `exclude_patterns` parameter and filter using `_matches_exclude`
    - Add `fetch_titles` parameter to skip provider lookups when disabled
    - Use `_classify_file` to categorize scanned files
    - Pass extracted year to provider chain for disambiguation
    - Track conflict metadata (flag + intended destination) when counter suffix is applied
    - _Requirements: 1.1–1.5, 2.2–2.5, 3.2–3.7, 4.1–4.5, 5.1–5.4, 6.1–6.7, 8.1, 10.4, 13.3, 13.5, 14.4_

- [ ] 5. Implement provider chain offline mode and TVMaze prefetch
  - [ ] 5.1 Add offline mode to `tvrenamer/providers/chain.py`
    - Add `_offline` flag and `enter_offline_mode()` method
    - Accept a `cache` parameter in constructor for cache-only lookups
    - When offline, skip all network calls and return cached results or empty string
    - Wire circuit breaker callback to trigger `enter_offline_mode()` after 5 consecutive failures
    - _Requirements: 17.1, 17.2, 17.3, 17.5_

  - [ ] 5.2 Implement season prefetch in `tvrenamer/providers/tvmaze.py`
    - Add `_prefetch_season(show_id, season)` method
    - Fetch all episodes for a season and populate cache entries using existing key format
    - Acquire rate-limiter tokens before prefetch requests
    - Fall back to individual lookups if prefetch fails or returns incomplete data
    - Accept `prefetch_seasons` config flag
    - _Requirements: 16.1, 16.2, 16.3, 16.4, 16.5_

  - [ ]* 5.3 Write unit tests for offline mode activation and prefetch
    - Test circuit breaker triggers offline mode
    - Test cache-only returns in offline mode
    - Test prefetch populates cache correctly
    - Mock API responses for prefetch scenarios
    - _Requirements: 16.2, 16.3, 16.4, 16.5, 17.1, 17.2, 17.3_

- [ ] 6. Implement cache integrity and versioning
  - [ ] 6.1 Extend `tvrenamer/cache.py` with version and checksum logic
    - Add `CACHE_VERSION = 1` and `META_KEY = "_meta"`
    - On persist: compute SHA-256 over sorted JSON of data entries (excluding `_meta`), write `_meta` entry with version and checksum
    - On load: validate version (discard data if outdated), validate checksum (rename to `.corrupt.{epoch}` if mismatch)
    - Handle filesystem errors gracefully during corrupt file rotation
    - _Requirements: 18.1, 18.2, 18.3, 18.4, 18.5_

  - [ ]* 6.2 Write property test for cache integrity round trip
    - **Property 10: Cache Integrity Round Trip**
    - **Validates: Requirements 18.1, 18.2, 18.3, 18.4**

- [ ] 7. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 8. Implement transaction history and undo support
  - [ ] 8.1 Implement `write_history_file()` in `tvrenamer/renamer/transaction.py`
    - Write `renamed_history_YYYYMMDD_HHMMSS.json` atomically after successful commit
    - Include `timestamp` (ISO 8601 with timezone), `run_id` (UUID), `renamed_files` array of `{original, new}` objects with absolute paths
    - Only write if `renamed_files` is non-empty
    - Log error (do NOT rollback) if history write fails
    - _Requirements: 12.1, 12.2, 12.3, 12.4, 12.5, 12.6_

  - [ ] 8.2 Implement undo logic (parse history file and produce reversal plan)
    - Parse history file, validate JSON schema (`renamed_files` array with `original`/`new` strings)
    - Generate reversal plan mapping `new` → `original`
    - Handle missing source files (skip with warning)
    - Handle existing destination conflicts (counter suffix with warning)
    - Use journaled transaction for execution
    - _Requirements: 11.1, 11.2, 11.3, 11.4, 11.5, 11.6, 11.7_

  - [ ]* 8.3 Write property test for rename-undo round trip
    - **Property 9: Rename-Undo Round Trip**
    - **Validates: Requirements 11.3, 12.4**

- [ ] 9. Implement CLI extensions and flag wiring
  - [ ] 9.1 Add new argparse flags to `tvrenamer/cli.py`
    - Add `--clean-junk` / `--trash-junk` (mutually exclusive)
    - Add `--undo <path>`
    - Add `--exclude <pattern>` (append action)
    - Add `--fetch-titles` / `-f` and `--no-fetch-titles` (mutually exclusive)
    - Add `--verbose` / `-v` and `--quiet` / `-q` (mutually exclusive)
    - Add `--strict-windows`
    - Add `--no-color`
    - Validate mutually exclusive flags, exit with code 4 on conflict
    - _Requirements: 7.5, 9.5, 10.1, 10.2, 10.9, 11.1, 13.1, 13.2, 14.1, 14.2, 14.3, 15.1, 15.2, 15.5, 20.1_

  - [ ] 9.2 Implement exit code resolution in `tvrenamer/cli.py`
    - Add `ExitCode` IntEnum (SUCCESS=0, NO_MEDIA=1, API_ERROR=2, FILE_ERROR=3, INVALID_ARGS=4)
    - Wrap `main()` execution with exception handling that maps exceptions to exit codes
    - When multiple errors occur, return the highest-priority (lowest non-zero) code
    - Write one-line failure summary to stderr on non-zero exit
    - _Requirements: 7.1, 7.2, 7.3, 7.4, 7.5, 7.6, 7.7_

  - [ ] 9.3 Implement colour-coded dry-run preview in `tvrenamer/cli.py`
    - Add `_should_color()` helper checking TTY, `NO_COLOR` env var, and `--no-color` flag
    - Render old filename in dim (SGR code 2) and new filename in green (SGR code 32)
    - Suppress all preview output when `--quiet` is active
    - Emit zero ANSI codes when colour is disabled
    - _Requirements: 9.1, 9.2, 9.3, 9.4, 9.5, 9.6_

  - [ ] 9.4 Implement conflict reporting in dry-run and execute modes
    - Prefix conflict-flagged entries with "[CONFLICT]" label
    - Show total conflict count summary when `--verbose` is set
    - Suppress conflict display when `--quiet` is set
    - _Requirements: 8.1, 8.2, 8.3, 8.4_

  - [ ] 9.5 Implement verbose and quiet output modes
    - `--verbose`: print provider URLs, response statuses, cache hit/miss, template resolution to stderr
    - `--quiet`: suppress previews, progress, info; emit only errors and data-loss warnings
    - _Requirements: 15.1, 15.2, 15.3, 15.4, 15.6_

  - [ ] 9.6 Wire junk cleanup logic in `tvrenamer/cli.py`
    - `--clean-junk`: delete junk-classified files
    - `--trash-junk`: move junk files to `.trash/` subdirectory in same parent
    - Log warning on filesystem errors, continue processing
    - Never modify video, subtitle, or unknown files
    - _Requirements: 10.1, 10.2, 10.5, 10.6, 10.7, 10.8, 10.9_

  - [ ] 9.7 Wire undo flag, exclude patterns, fetch-titles, and strict-windows into main flow
    - `--undo`: display dry-run or execute reversal using history file
    - `--exclude`: pass patterns to engine's `exclude_patterns`
    - `--fetch-titles` / `--no-fetch-titles`: pass flag to engine
    - `--strict-windows`: pass to sanitizer via engine
    - Merge CLI and config values with proper precedence (CLI > config > defaults)
    - _Requirements: 11.1, 11.2, 11.3, 13.1, 13.2, 13.4, 13.5, 13.6, 14.1, 14.2, 14.3, 14.4, 14.5, 14.6, 20.1, 20.2, 20.3, 20.4, 20.5_

- [ ] 10. Implement crash recovery prompts
  - [ ] 10.1 Implement journal detection and interactive recovery prompt in `tvrenamer/cli.py`
    - Detect pending journals on startup (outside `--resume`/`--rollback` mode)
    - Interactive mode: prompt user to choose resume/rollback/ignore
    - Non-interactive mode: log warning, suggest `--resume`/`--rollback`, proceed
    - Resume: execute pending journals oldest-first
    - Rollback: rollback pending journals newest-first
    - Handle per-journal failures gracefully (log, skip, continue)
    - _Requirements: 19.1, 19.2, 19.3, 19.4, 19.5, 19.6, 19.7, 19.8_

  - [ ]* 10.2 Write unit tests for crash recovery prompts
    - Mock stdin for interactive prompt testing
    - Test non-interactive warning logging
    - Test resume/rollback/ignore behavior
    - _Requirements: 19.1, 19.2, 19.3, 19.4, 19.5, 19.6, 19.7, 19.8_

- [ ] 11. Checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

- [ ] 12. Integration wiring and end-to-end validation
  - [ ] 12.1 Wire offline mode warning to verbose output
    - When offline mode activates and `--verbose` is set, print "WARNING: Offline mode activated — serving cached results only" to stderr
    - _Requirements: 17.4_

  - [ ] 12.2 Wire year to provider search and template
    - Pass extracted year to `ProviderChain.get_episode_title` (via `search_show`) for disambiguation
    - Ensure `{year}`/`{y}` token works in templates with proper fallback (empty string + separator cleanup)
    - _Requirements: 4.3, 4.4, 4.5_

  - [ ] 12.3 Ensure `execute_transaction` calls `write_history_file` on successful commit
    - Integrate history write as post-commit step in transaction flow
    - _Requirements: 12.1, 12.3_

  - [ ]* 12.4 Write integration tests for end-to-end CLI scenarios
    - Test full rename with temp directory tree
    - Test undo round-trip on real filesystem
    - Test exit codes for each error scenario
    - Test junk cleanup (delete and trash)
    - Test verbose/quiet output
    - _Requirements: 7.1–7.7, 10.1–10.8, 11.1–11.7, 15.1–15.6_

- [ ] 13. Final checkpoint - Ensure all tests pass
  - Ensure all tests pass, ask the user if questions arise.

## Notes

- Tasks marked with `*` are optional and can be skipped for faster MVP
- Each task references specific requirements for traceability
- Checkpoints ensure incremental validation
- Property tests validate universal correctness properties from the design document
- Unit tests validate specific examples and edge cases
- The project uses `pytest` and `hypothesis` for testing
- All code targets the existing Python project structure — no new packages introduced

## Task Dependency Graph

```json
{
  "waves": [
    { "id": 0, "tasks": ["1.1", "1.2"] },
    { "id": 1, "tasks": ["1.3", "2.1", "2.5", "2.7", "2.9", "2.11", "4.1", "4.3"] },
    { "id": 2, "tasks": ["2.2", "2.3", "2.4", "2.6", "2.8", "2.10", "2.12", "4.2", "4.4"] },
    { "id": 3, "tasks": ["4.5", "5.1", "5.2", "6.1"] },
    { "id": 4, "tasks": ["5.3", "6.2", "8.1"] },
    { "id": 5, "tasks": ["8.2", "8.3"] },
    { "id": 6, "tasks": ["9.1", "9.2", "9.3", "9.4", "9.5", "9.6", "9.7"] },
    { "id": 7, "tasks": ["10.1", "10.2"] },
    { "id": 8, "tasks": ["12.1", "12.2", "12.3"] },
    { "id": 9, "tasks": ["12.4"] }
  ]
}
```
