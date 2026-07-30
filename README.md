# Eids-TV-Renamer

![CI](https://github.com/eidleweise/Eids-TV-Renamer/actions/workflows/ci.yml/badge.svg?branch=main)

A robust, cross-platform Python utility that recursively scans, cleans, renames, and organizes TV show episode files and their associated subtitles. Fetches official episode titles from TVMaze, Wikidata, and Wikipedia — no API keys required.

## Features

- **Smart Pattern Extraction** — Detects SxxExx, NxNN, multi-episode ranges, and part indicators from filenames and folder structures
- **Multi-Provider Metadata** — Queries TVMaze, Wikidata SPARQL, and Wikipedia in configurable order; first match wins
- **Subtitle Pairing** — Automatically matches `.srt`, `.vtt`, `.ass` etc. to their video file, preserving language tags (`.en.srt`)
- **Multipart Grouping** — Groups split files (Part 1, Part 2, CD1, CD2) and renames with explicit part suffixes
- **Journaled Atomic Renames** — All-or-nothing transactions with crash recovery, rollback, and undo support
- **Disk Cache** — JSON-based with TTL, LRU eviction, atomic writes, and stale-while-revalidate
- **Rate Limiting** — Per-provider token bucket with circuit breaker and exponential backoff
- **Structured Logging** — JSON log files with rotation, secret redaction, and run-level correlation IDs
- **Dry-Run by Default** — Preview all changes before committing; colour-coded terminal output
- **Configurable via TOML** — Set defaults for template, providers, paths, and more
- **Interactive & Scripting Modes** — Wizard prompts for manual use, flags for automation/cron

## Quick Start

```bash
# Clone the repo
git clone https://github.com/eidleweise/Eids-TV-Renamer.git
cd Eids-TV-Renamer

# Use the run script (creates venv, installs deps, runs the tool)
./run.sh --path ~/Videos/MyShow/ --template "{show} - S{season}E{episode} - {title}{ext}"

# Or install manually
python3 -m venv .venv && source .venv/bin/activate
pip install -e .
tvrenamer --path ~/Videos/MyShow/
```

## Installation

Requires **Python 3.11+** (uses `tomllib` from the standard library).

```bash
pip install -e .
```

This installs the `tvrenamer` command globally in your environment.

## Usage

```bash
# Dry-run preview (default)
tvrenamer --path /media/tv/Breaking\ Bad/

# Execute renames
tvrenamer --path /media/tv/Breaking\ Bad/ --execute

# Custom template with short aliases
tvrenamer -p ./shows -t "{show} - S{s}E{e} - {t}{ext}" -x

# Skip online lookups (offline rename)
tvrenamer -p ./shows --no-fetch-titles -x

# Interactive wizard mode
tvrenamer --interactive

# Undo a previous run
tvrenamer --undo renamed_history_20260730_141500.json --execute

# Resume or rollback interrupted transactions
tvrenamer --path ./shows --resume
tvrenamer --path ./shows --rollback
```

## CLI Flags

| Flag | Short | Description |
|------|-------|-------------|
| `--path` | `-p` | Target directory to scan (default: `.`) |
| `--template` | `-t` | Filename template (see tokens below) |
| `--execute` | `-x` | Perform renames (default is dry-run) |
| `--config` | `-c` | Path to TOML config file |
| `--providers-order` | | Comma-separated provider order |
| `--fetch-titles` | `-f` | Enable metadata lookups (default) |
| `--no-fetch-titles` | | Skip all API queries |
| `--exclude` | | Glob pattern for files to skip (repeatable) |
| `--clean-junk` | | Delete junk files (.nfo, .txt, .url, etc.) |
| `--trash-junk` | | Move junk files to `.trash/` instead |
| `--undo` | | Path to history JSON; reverses renames |
| `--resume` | | Resume pending transaction journals |
| `--rollback` | | Rollback pending/failed journals |
| `--strict-windows` | | Enable Windows-safe filename rules |
| `--verbose` | `-v` | Detailed output (API calls, cache info) |
| `--quiet` | `-q` | Suppress all output except errors |
| `--no-color` | | Disable ANSI colour codes |
| `--interactive` | `-i` | Run the interactive wizard |
| `--log-file` | | Custom log file path |
| `--log-level` | | Log level: DEBUG, INFO, WARN, ERROR |

## Template Tokens

| Token | Alias | Description |
|-------|-------|-------------|
| `{show}` | | Cleaned show name |
| `{season}` | `{s}` | Two-digit padded season (01) |
| `{episode}` | `{e}` | Two-digit padded episode (02) |
| `{title}` | `{t}` | Episode title from provider |
| `{year}` | `{y}` | Show premiere year |
| `{ext}` | | Original extension with dot (.mkv) |

**Examples:**

```
"{show} - S{season}E{episode} - {title}{ext}"  →  Breaking Bad - S01E01 - Pilot.mkv
"{show} ({year}) - S{s}E{e}{ext}"              →  Battlestar Galactica (2003) - S01E01.mkv
```

## Configuration

Place a `.tvrenamer.toml` file in the target directory or your home directory. CLI flags override config values.

```toml
[defaults]
template = "{show} - S{season}E{episode} - {title}{ext}"
fetch_titles = true
strict_windows = false
space_replacement = "underscore"
# exclude_patterns = ["*sample*", "*extras*"]

[providers]
order = ["tvmaze", "wikidata", "wikipedia"]

[provider.tvmaze]
prefetch_seasons = true

[junk]
extensions = [".nfo", ".txt", ".url", ".jpg", ".png", ".sfv"]

[scene_tags]
strip = ["PROPER", "REPACK", "WEB-DL", "WEBRip", "HDTV", "BluRay", "x264", "x265", "HEVC", "720p", "1080p", "2160p"]
group_tag_patterns = ["\\[.*?\\]", "-\\w+$"]

[path_extraction]
directory_blacklist = ["Downloads", "TV Shows", "Completed", "Desktop"]
```

## How It Works

1. **Scan** — Recursively walks the target directory, classifying files as Video, Subtitle, Junk, or Unknown
2. **Extract** — Regex cascade extracts show name, season, and episode from filenames and folder structure
3. **Clean** — Strips scene tags, normalizes separators, extracts year, applies title casing
4. **Lookup** — Queries providers in order (TVMaze → Wikidata → Wikipedia) with caching and rate limiting
5. **Format** — Applies the template, sanitizes the filename, pairs subtitles
6. **Preview** — Shows a colour-coded dry-run of all planned changes
7. **Execute** — Performs atomic renames via a journaled transaction with rollback on failure

## Exit Codes

| Code | Meaning |
|------|---------|
| 0 | Success |
| 1 | No media files found |
| 2 | API/provider errors |
| 3 | File operation errors |
| 4 | Invalid arguments or config |

## Development

```bash
# Setup
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
pip install -e .

# Run tests
pytest

# Lint & format
black .
flake8 tvrenamer tests
mypy --ignore-missing-imports tvrenamer
```

## Project Structure

```
tvrenamer/
├── cli.py              # CLI entry point, argparse, interactive wizard
├── config.py           # TOML config loading
├── cache.py            # Disk cache (JSON, TTL, LRU, atomic writes)
├── sanitize.py         # Cross-platform filename sanitization
├── ratelimit.py        # Token bucket, circuit breaker, backoff
├── logging_setup.py    # Structured JSON logging, redaction
├── exceptions.py       # Typed exceptions mapped to exit codes
├── providers/
│   ├── base.py         # MetadataProvider interface
│   ├── chain.py        # ProviderChain (ordered, first-wins)
│   ├── tvmaze.py       # TVMaze API provider
│   ├── wikidata.py     # Wikidata search + SPARQL fallback
│   └── wikipedia.py    # Wikipedia OpenSearch + summary
└── renamer/
    ├── engine.py       # Scanning, extraction, planning
    └── transaction.py  # Journaled atomic renames, rollback, undo
tests/
    └── test_*.py       # Unit + property-based tests (hypothesis)
```

## Built With AI

This project is an experiment in **agentic engineering** — the entire codebase, architecture, tests, and documentation were developed collaboratively with AI (Kiro). A human provided direction, made design decisions, and reviewed output, while the AI handled implementation, spec writing, and iteration. It's a practical exploration of what AI-assisted solo development looks like for a real, personal-use tool. 
- Personal hand written comment - Honestly I think it's a tad verbose.. AI sure likes to hear itself talk. But equally I'd never even want to write all this!!!

## License

See [LICENSE](LICENSE) for details.
