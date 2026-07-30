"""CLI entry point for tvrenamer.

Supports both interactive wizard and non-interactive flag-driven modes.
"""

import argparse
import os
import re
import sys
import glob
import json
import logging
import shutil

from .config import load_config, get_defaults, get_junk_extensions
from .cache import DiskCache
from .exceptions import (
    ExitCode,
    TVRenamerError,
    NoMediaFoundError,
    ProviderError,
    FileOperationError,
    InvalidConfigError,
)
from .renamer.engine import (
    plan_renames,
    perform_transaction_for_plan,
    build_providers_from_config,
    _classify_file,
    VIDEO_EXTS,
    SUBTITLE_EXTS,
)
from .renamer.transaction import (
    execute_transaction,
    rollback_transaction,
    write_history_file,
    parse_history_file,
    build_undo_plan,
    build_transaction,
    write_journal_atomically,
    _read_journal,
)


# --- Colour helpers ---


def _should_color(args) -> bool:
    """Determine if ANSI colour should be used."""
    if getattr(args, "no_color", False):
        return False
    if os.environ.get("NO_COLOR", ""):
        return False
    if not hasattr(sys.stdout, "isatty") or not sys.stdout.isatty():
        return False
    return True


def _dim(text: str, use_color: bool) -> str:
    if use_color:
        return f"\033[2m{text}\033[0m"
    return text


def _green(text: str, use_color: bool) -> str:
    if use_color:
        return f"\033[32m{text}\033[0m"
    return text


def _yellow(text: str, use_color: bool) -> str:
    if use_color:
        return f"\033[33m{text}\033[0m"
    return text


# --- Journal detection ---


def find_journals(root: str, states: list = None):
    """Find transaction journal files with given states in root directory."""
    if states is None:
        states = ["pending"]
    pattern = os.path.join(root, "transaction_*.json")
    paths = glob.glob(pattern)
    out = []
    for p in paths:
        try:
            with open(p, "r") as f:
                data = json.load(f)
            if data.get("state") in states:
                out.append(p)
        except Exception:
            continue
    return out


# --- Junk cleanup ---


def _cleanup_junk(root: str, mode: str, junk_extensions: set, exclude_patterns: list):
    """Delete or trash junk files.

    Args:
        mode: "clean" for permanent delete, "trash" for move to .trash/
    """
    import fnmatch

    count = 0
    for dirpath, dirs, files in os.walk(root):
        for fname in files:
            _, ext = os.path.splitext(fname)
            if ext.lower() not in junk_extensions:
                continue
            src = os.path.join(dirpath, fname)

            # Check exclude patterns
            try:
                relpath = os.path.relpath(src, root)
            except ValueError:
                relpath = fname
            if exclude_patterns:
                from .renamer.engine import _matches_exclude
                if _matches_exclude(relpath, exclude_patterns):
                    continue

            try:
                if mode == "clean":
                    os.unlink(src)
                    logging.debug("Deleted junk file: %s", src)
                elif mode == "trash":
                    trash_dir = os.path.join(dirpath, ".trash")
                    os.makedirs(trash_dir, exist_ok=True)
                    shutil.move(src, os.path.join(trash_dir, fname))
                    logging.debug("Trashed junk file: %s", src)
                count += 1
            except OSError as e:
                logging.warning("Failed to %s junk file %s: %s", mode, src, e)

    return count


# --- Preview display ---


def _display_preview(plan, args, use_color: bool):
    """Display dry-run preview with colour coding and conflict reporting."""
    if getattr(args, "quiet", False):
        return

    # Sort by destination path for readable output (season → episode order)
    sorted_plan = sorted(plan, key=lambda pair: pair[1])

    conflict_count = 0
    for src, dst in sorted_plan:
        src_name = os.path.basename(src)
        dst_name = os.path.basename(dst)

        # Detect conflict by checking for our specific counter suffix format " (N).ext"
        # This avoids false positives on episode titles containing parenthesized numbers
        is_conflict = bool(re.search(r" \(\d+\)\.\w+$", dst_name))
        if is_conflict:
            conflict_count += 1

        prefix = ""
        if is_conflict:
            prefix = _yellow("[CONFLICT] ", use_color)

        line = f"{prefix}{_dim(src_name, use_color)} → {_green(dst_name, use_color)}"
        print(line)

    if conflict_count > 0 and getattr(args, "verbose", False):
        print(f"\n{conflict_count} conflict(s) required counter suffixes.")


# --- Crash Recovery ---


def _handle_pending_journals(root: str, args):
    """Detect pending journals and prompt user or log warning.

    Req 19: On startup (outside --resume/--rollback mode), detect uncommitted
    journals and offer to resume, rollback, or ignore.
    """
    pending = find_journals(root, states=["pending"])
    if not pending:
        return  # No pending journals — proceed normally

    # Notify user about pending journals
    count = len(pending)

    if args.interactive:
        # Interactive mode: prompt for action
        print(
            f"\nWARNING: {count} pending transaction journal(s) detected:",
            file=sys.stderr,
        )
        for j in sorted(pending):
            print(f"  {j}", file=sys.stderr)

        print("\nOptions:", file=sys.stderr)
        print("  [r]esume  - Complete the pending transactions (oldest first)", file=sys.stderr)
        print("  [b]ack    - Rollback the pending transactions (newest first)", file=sys.stderr)
        print("  [i]gnore  - Leave journals unchanged and proceed", file=sys.stderr)

        try:
            choice = input("\nChoose action [r/b/i]: ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            choice = "i"

        if choice in ("r", "resume"):
            for j in sorted(pending):
                try:
                    execute_transaction(j)
                    if not args.quiet:
                        print(f"  Resumed: {os.path.basename(j)}", file=sys.stderr)
                except Exception as e:
                    logging.error("Error resuming journal %s: %s", j, e)
                    print(f"  FAILED to resume: {os.path.basename(j)} ({e})", file=sys.stderr)

        elif choice in ("b", "back", "rollback"):
            for j in sorted(pending, reverse=True):
                try:
                    rollback_transaction(j)
                    if not args.quiet:
                        print(f"  Rolled back: {os.path.basename(j)}", file=sys.stderr)
                except Exception as e:
                    logging.error("Error rolling back journal %s: %s", j, e)
                    print(f"  FAILED to rollback: {os.path.basename(j)} ({e})", file=sys.stderr)

        else:
            # "ignore" or any other input — leave journals unchanged
            if not args.quiet:
                print("  Ignoring pending journals, proceeding with current run.", file=sys.stderr)

    else:
        # Non-interactive mode: log warning and proceed
        logging.warning(
            "%d pending transaction journal(s) detected. "
            "Use --resume or --rollback to handle them.",
            count,
        )
        if not args.quiet:
            print(
                f"WARNING: {count} pending journal(s) found. "
                f"Use --resume or --rollback to handle them.",
                file=sys.stderr,
            )


# --- Main ---


def main(argv=None):
    p = argparse.ArgumentParser(prog="tvrenamer", description="TV episode file renamer")
    p.add_argument("--path", "-p", default=None, help="Target directory to scan")
    p.add_argument("--config", "-c", default=None, help="Path to config TOML")
    p.add_argument(
        "--execute", "-x", action="store_true", default=None,
        help="Perform renames (default dry-run)",
    )
    p.add_argument("--template", "-t", default=None, help="Renaming template")
    p.add_argument(
        "--providers", default=None,
        help="Comma-separated provider order (e.g., tvmaze,wikidata,wikipedia)",
    )
    p.add_argument(
        "--space-replacement", default=None, choices=["underscore", "none"],
        help="Replace spaces in filenames: 'underscore' or 'none'",
    )

    # Fetch titles control (mutually exclusive)
    fetch_group = p.add_mutually_exclusive_group()
    fetch_group.add_argument(
        "--fetch-titles", "-f", action="store_true", default=None,
        help="Fetch episode titles from metadata providers",
    )
    fetch_group.add_argument(
        "--no-fetch-titles", action="store_true", default=False,
        help="Skip online API queries",
    )

    # Junk cleanup (mutually exclusive)
    junk_group = p.add_mutually_exclusive_group()
    junk_group.add_argument(
        "--clean-junk", action="store_true", default=False,
        help="Permanently delete junk files",
    )
    junk_group.add_argument(
        "--trash-junk", action="store_true", default=False,
        help="Move junk files to .trash/ subdirectory",
    )

    # Verbose / quiet (mutually exclusive)
    output_group = p.add_mutually_exclusive_group()
    output_group.add_argument(
        "--verbose", "-v", action="store_true", default=False,
        help="Show detailed output including API responses",
    )
    output_group.add_argument(
        "--quiet", "-q", action="store_true", default=False,
        help="Suppress all output except errors",
    )

    # Exclude patterns
    p.add_argument(
        "--exclude", action="append", default=None,
        help="Glob pattern for files to skip (repeatable)",
    )

    # Undo
    p.add_argument(
        "--undo", default=None, metavar="HISTORY_FILE",
        help="Path to a JSON history file; reverses all renames",
    )

    # Strict Windows mode
    p.add_argument(
        "--strict-windows", action="store_true", default=None,
        help="Activate Windows-compatible filename sanitization",
    )

    # No colour
    p.add_argument(
        "--no-color", action="store_true", default=False,
        help="Disable ANSI colour output",
    )

    # Resume / rollback
    p.add_argument(
        "--resume", action="store_true", help="Resume pending transaction journals",
    )
    p.add_argument(
        "--rollback", action="store_true", help="Rollback pending/failed journals",
    )

    # Logging
    p.add_argument("--log-file", default=None, help="Path to write logs")
    p.add_argument("--log-level", default=None, help="Logging level (DEBUG, INFO, WARN, ERROR)")

    # Interactive
    p.add_argument(
        "--interactive", "-i", action="store_true", help="Run interactive wizard",
    )

    args = p.parse_args(argv)

    # --- Argument validation ---
    try:
        return _run(args)
    except InvalidConfigError as e:
        print(f"Error: {e}", file=sys.stderr)
        return ExitCode.INVALID_ARGS
    except NoMediaFoundError as e:
        print(f"Error: {e}", file=sys.stderr)
        return ExitCode.NO_MEDIA
    except ProviderError as e:
        print(f"Error: {e}", file=sys.stderr)
        return ExitCode.API_ERROR
    except FileOperationError as e:
        print(f"Error: {e}", file=sys.stderr)
        return ExitCode.FILE_ERROR
    except TVRenamerError as e:
        print(f"Error: {e}", file=sys.stderr)
        return getattr(e, "exit_code", 1)


def _run(args):
    """Internal main logic. Raises typed exceptions for exit code mapping."""

    # Validate exclude patterns
    if args.exclude:
        import fnmatch
        for pat in args.exclude:
            try:
                fnmatch.translate(pat)
            except Exception:
                raise InvalidConfigError(f"Invalid exclude pattern: {pat}")

    # --- Load config first (source of all defaults) ---
    # Use explicit --config if provided, otherwise search from --path or cwd
    initial_root = os.path.abspath(args.path) if args.path else os.path.abspath(".")
    config = load_config(args.config, initial_root)
    cfg_defaults = get_defaults(config)

    # --- Resolve all options: CLI flag > config value > hardcoded default ---
    # Each option uses None to mean "not specified by user on CLI"

    # Path: --path overrides config.defaults.path, falls back to interactive prompt or "."
    if args.path is not None:
        root = os.path.abspath(args.path)
    elif config.get("defaults", {}).get("path"):
        cfg_path = os.path.expanduser(config["defaults"]["path"])
        if os.path.isdir(cfg_path):
            root = os.path.abspath(cfg_path)
        else:
            raise InvalidConfigError(f"Config path directory does not exist: {cfg_path}")
    elif args.interactive:
        # No path from CLI or config — ask the user
        try:
            inp = input("Target directory to scan: ").strip()
            if inp:
                expanded = os.path.expanduser(inp)
                if os.path.isdir(expanded):
                    root = os.path.abspath(expanded)
                else:
                    raise InvalidConfigError(f"Directory does not exist: {inp}")
            else:
                raise InvalidConfigError("No target directory provided.")
        except (EOFError, KeyboardInterrupt):
            raise InvalidConfigError("No target directory provided.")
    else:
        root = os.path.abspath(".")

    # Execute: --execute overrides config.defaults.execute, default False
    if args.execute is not None:
        execute = args.execute
    elif args.interactive:
        try:
            default_exec = "y" if config.get("defaults", {}).get("execute") else "n"
            inp = input(f"Execute renames (not just dry-run)? [y/N] ({default_exec}): ").strip().lower()
            if inp in ("y", "yes"):
                execute = True
            elif inp in ("n", "no"):
                execute = False
            else:
                execute = bool(config.get("defaults", {}).get("execute", False))
        except (EOFError, KeyboardInterrupt):
            execute = False
    else:
        execute = bool(config.get("defaults", {}).get("execute", False))

    # Template: --template overrides config.defaults.template
    default_template = config.get("defaults", {}).get("template") or "{show} - S{season}E{episode} - {title}{ext}"
    if args.template:
        template = args.template
    elif args.interactive:
        try:
            inp = input(f"Filename template [{default_template}]: ").strip()
            template = inp if inp else default_template
        except (EOFError, KeyboardInterrupt):
            template = default_template
    else:
        template = default_template

    # Providers: --providers overrides config.providers.order
    default_providers = config.get("providers", {}).get("order") or ["tvmaze", "wikidata", "wikipedia"]
    if args.providers:
        provider_order = [x.strip() for x in args.providers.split(",") if x.strip()]
    elif args.interactive:
        try:
            default_str = ",".join(default_providers)
            inp = input(f"Providers order [{default_str}]: ").strip()
            if inp:
                provider_order = [x.strip() for x in inp.split(",") if x.strip()]
            else:
                provider_order = default_providers
        except (EOFError, KeyboardInterrupt):
            provider_order = default_providers
    else:
        provider_order = default_providers if default_providers != ["tvmaze", "wikidata", "wikipedia"] else None

    # Fetch titles: --fetch-titles/--no-fetch-titles overrides config.defaults.fetch_titles
    if args.no_fetch_titles:
        fetch_titles = False
    elif args.fetch_titles:
        fetch_titles = True
    elif args.interactive:
        try:
            default_fetch = cfg_defaults.get("fetch_titles", True)
            default_str = "Y" if default_fetch else "n"
            inp = input(f"Fetch episode titles from online providers? [{default_str}]: ").strip().lower()
            if inp in ("y", "yes"):
                fetch_titles = True
            elif inp in ("n", "no"):
                fetch_titles = False
            else:
                fetch_titles = default_fetch
        except (EOFError, KeyboardInterrupt):
            fetch_titles = True
    else:
        fetch_titles = cfg_defaults.get("fetch_titles", True)

    # Space replacement: --space-replacement overrides config.defaults.space_replacement
    if args.space_replacement is not None:
        space_replacement = "underscore" if args.space_replacement == "underscore" else None
    elif args.interactive:
        try:
            cfg_sr = cfg_defaults.get("space_replacement", "")
            default_sr = "underscore" if str(cfg_sr).lower() in ("underscore", "underscores", "_") else "none"
            default_str = "Y" if default_sr == "underscore" else "n"
            inp = input(f"Replace spaces with underscores? [{default_str}]: ").strip().lower()
            if inp in ("y", "yes"):
                space_replacement = "underscore"
            elif inp in ("n", "no"):
                space_replacement = None
            else:
                space_replacement = "underscore" if default_sr == "underscore" else None
        except (EOFError, KeyboardInterrupt):
            space_replacement = None
    else:
        cfg_sr = cfg_defaults.get("space_replacement", "")
        space_replacement = "underscore" if str(cfg_sr).lower() in ("underscore", "underscores", "_") else None

    # Strict Windows: --strict-windows overrides config.defaults.strict_windows
    if args.strict_windows is not None:
        strict_windows = args.strict_windows
    else:
        strict_windows = cfg_defaults.get("strict_windows", False)

    # Exclude patterns: CLI patterns + config patterns (union)
    exclude_patterns = list(args.exclude or [])
    exclude_patterns.extend(cfg_defaults.get("exclude_patterns", []))

    # Log level: --log-level overrides default INFO
    log_level = args.log_level or "INFO"

    # Junk extensions from config
    junk_extensions = set(e.lower() for e in get_junk_extensions(config))

    # --- Setup logging ---
    log_file = args.log_file or os.path.join(root, ".tvrenamer.log")
    import uuid
    run_id = uuid.uuid4().hex
    from .logging_setup import setup_json_logging, set_run_id
    setup_json_logging(log_file, level=log_level)
    set_run_id(run_id)

    # In verbose mode, add a stderr handler so WARNING+ messages are visible
    if args.verbose:
        stderr_handler = logging.StreamHandler(sys.stderr)
        stderr_handler.setLevel(logging.WARNING)
        stderr_handler.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        logging.getLogger().addHandler(stderr_handler)

    use_color = _should_color(args)

    # --- Handle --undo ---
    if args.undo:
        history_data = parse_history_file(args.undo)
        undo_plan = build_undo_plan(history_data, allowed_root=root)

        if not undo_plan:
            if not args.quiet:
                print("No files to undo (all source files missing).", file=sys.stderr)
            return ExitCode.SUCCESS

        if not execute:
            # Dry-run preview of undo
            if not args.quiet:
                print("Undo dry-run preview:")
                for src, dst in undo_plan:
                    print(f"  {_dim(os.path.basename(src), use_color)} → {_green(os.path.basename(dst), use_color)}")
                print(f"\n{len(undo_plan)} file(s) would be restored. Use --execute to apply.")
        else:
            # Execute undo
            journal = build_transaction(undo_plan, run_id=run_id)
            journal_path = write_journal_atomically(journal, root)
            try:
                execute_transaction(journal_path)
                if not args.quiet:
                    print(f"Undo complete: {len(undo_plan)} file(s) restored.")
            except Exception as e:
                raise FileOperationError(f"Undo failed: {e}")

        return ExitCode.SUCCESS

    # --- Handle --resume / --rollback ---
    if args.resume or args.rollback:
        if args.resume:
            journals = find_journals(root, states=["pending"])
            if not journals:
                if not args.quiet:
                    logging.info("No pending journals to resume")
            for j in sorted(journals):
                try:
                    execute_transaction(j)
                    if not args.quiet:
                        logging.info("Resumed journal: %s", j)
                except Exception as e:
                    logging.error("Error resuming journal %s: %s", j, e)

        if args.rollback:
            journals = find_journals(root, states=["pending", "failed"])
            if not journals:
                if not args.quiet:
                    logging.info("No journals to rollback")
            for j in sorted(journals, reverse=True):
                try:
                    rollback_transaction(j)
                    if not args.quiet:
                        logging.info("Rolled back journal: %s", j)
                except Exception as e:
                    logging.error("Error rolling back journal %s: %s", j, e)

        return ExitCode.SUCCESS

    # --- Crash Recovery: Detect pending journals on startup ---
    _handle_pending_journals(root, args)

    # --- Main rename flow ---

    # Setup cache and providers
    cache_path = os.path.join(root, ".tvrenamer_cache.json")
    cache = DiskCache(cache_path)

    providers = build_providers_from_config(cache, config=config, order_override=provider_order)

    # Verbose: log provider info
    if args.verbose:
        print(f"Providers: {[type(p).__name__ for p in providers]}", file=sys.stderr)
        print(f"Template: {template}", file=sys.stderr)
        print(f"Fetch titles: {fetch_titles}", file=sys.stderr)
        print(f"Strict Windows: {strict_windows}", file=sys.stderr)
        if exclude_patterns:
            print(f"Exclude patterns: {exclude_patterns}", file=sys.stderr)

    # Plan renames
    plan = plan_renames(
        root,
        template=template,
        cache=cache,
        providers=providers,
        space_replacement=space_replacement,
        exclude_patterns=exclude_patterns,
        fetch_titles=fetch_titles,
        config=config,
        strict_windows=strict_windows,
        junk_extensions=junk_extensions,
    )

    if not plan:
        raise NoMediaFoundError(f"No media files found in {root}")

    # Display preview
    if not execute:
        _display_preview(plan, args, use_color)
        if not args.quiet:
            print(f"\n{len(plan)} file(s) would be renamed. Use --execute to apply.")
    else:
        # Show preview before executing (unless quiet)
        if not args.quiet:
            _display_preview(plan, args, use_color)
            print(f"\nExecuting {len(plan)} rename(s)...")

        # Execute transaction
        try:
            journal_path, _ = perform_transaction_for_plan(root, plan, execute=True)
        except Exception as e:
            raise FileOperationError(f"Rename failed: {e}")

        # Write history file
        try:
            committed_journal = _read_journal(journal_path)
            history_path = write_history_file(committed_journal, root)
            if history_path and args.verbose:
                print(f"History written: {history_path}", file=sys.stderr)
        except Exception as e:
            logging.error("Failed to write history file: %s", e)

        if not args.quiet:
            print(f"Done. {len(plan)} file(s) renamed.")

    # --- Junk cleanup ---
    if args.clean_junk or args.trash_junk:
        mode = "clean" if args.clean_junk else "trash"
        count = _cleanup_junk(root, mode, junk_extensions, exclude_patterns)
        if not args.quiet:
            action = "deleted" if mode == "clean" else "trashed"
            print(f"{count} junk file(s) {action}.")

    return ExitCode.SUCCESS


if __name__ == "__main__":
    sys.exit(main())
