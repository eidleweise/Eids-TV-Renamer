"""Property tests for rename-undo round trip.

# Feature: design-gap-completion, Property 9: Rename-Undo Round Trip

Validates: Requirements 11.3, 12.4
"""

import os
import json
import tempfile

from hypothesis import given, assume, settings
from hypothesis import strategies as st

from tvrenamer.renamer.transaction import (
    build_transaction,
    write_journal_atomically,
    execute_transaction,
    write_history_file,
    parse_history_file,
    build_undo_plan,
    _read_journal,
)


# --- Strategies ---

# Generate safe filenames (no path separators, no dots at start)
safe_names = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789_-",
    min_size=2, max_size=20,
)

# Generate file extensions
extensions = st.sampled_from([".mkv", ".mp4", ".avi", ".srt", ".txt"])

# Generate rename plans (pairs of original → new names)
# Ensure no destination name matches any source name (avoids cross-rename conflicts)
rename_pairs = st.lists(
    st.tuples(safe_names, safe_names, extensions),
    min_size=1, max_size=10,
    unique_by=lambda t: t[0],  # unique source names
).filter(
    # Ensure src != dst for each pair
    lambda pairs: all(p[0] != p[1] for p in pairs)
).filter(
    # Ensure unique destination names
    lambda pairs: len({p[1] for p in pairs}) == len(pairs)
).filter(
    # Ensure no dst name collides with any src name (avoids cross-rename conflicts)
    lambda pairs: not ({p[1] for p in pairs} & {p[0] for p in pairs})
)


class TestRenameUndoRoundTrip:
    """Property 9: For any successful rename transaction that produces a history file,
    parsing that history file and executing the undo operation SHALL produce a plan
    that maps each 'new' path back to its 'original' path.
    """

    @settings(max_examples=50)
    @given(pairs=rename_pairs)
    def test_history_is_invertible(self, pairs):
        """The history file contains a faithful invertible record of the rename."""
        with tempfile.TemporaryDirectory() as d:
            # Create source files
            sources = []
            for src_name, dst_name, ext in pairs:
                src_path = os.path.join(d, f"{src_name}{ext}")
                dst_path = os.path.join(d, f"{dst_name}{ext}")
                with open(src_path, "w") as f:
                    f.write(f"content:{src_name}")
                sources.append((src_path, dst_path))

            # Execute transaction
            journal = build_transaction(sources, run_id="test-run")
            journal_path = write_journal_atomically(journal, d)
            execute_transaction(journal_path)

            # Write history
            committed = _read_journal(journal_path)
            history_path = write_history_file(committed, d)
            assert history_path is not None

            # Parse history and build undo plan
            history_data = parse_history_file(history_path)
            undo_plan = build_undo_plan(history_data)

            # Verify undo plan maps each new→original
            assert len(undo_plan) == len(sources)
            for (src_orig, dst_renamed), (undo_src, undo_dst) in zip(sources, undo_plan):
                assert undo_src == dst_renamed, (
                    f"Undo source should be '{dst_renamed}', got '{undo_src}'"
                )
                assert undo_dst == src_orig, (
                    f"Undo destination should be '{src_orig}', got '{undo_dst}'"
                )

    @settings(max_examples=50)
    @given(pairs=rename_pairs)
    def test_undo_restores_files(self, pairs):
        """Executing the undo plan restores files to original locations."""
        with tempfile.TemporaryDirectory() as d:
            sources = []
            contents = {}
            for src_name, dst_name, ext in pairs:
                src_path = os.path.join(d, f"{src_name}{ext}")
                dst_path = os.path.join(d, f"{dst_name}{ext}")
                content = f"content:{src_name}"
                with open(src_path, "w") as f:
                    f.write(content)
                sources.append((src_path, dst_path))
                contents[src_path] = content

            # Execute rename
            journal = build_transaction(sources, run_id="test-run")
            journal_path = write_journal_atomically(journal, d)
            execute_transaction(journal_path)

            # Write history
            committed = _read_journal(journal_path)
            history_path = write_history_file(committed, d)

            # Build and execute undo
            history_data = parse_history_file(history_path)
            undo_plan = build_undo_plan(history_data)

            undo_journal = build_transaction(undo_plan, run_id="undo-run")
            undo_journal_path = write_journal_atomically(undo_journal, d)
            execute_transaction(undo_journal_path)

            # Verify files are back in original locations with correct content
            for src_path, content in contents.items():
                assert os.path.exists(src_path), (
                    f"Original file not restored: {src_path}"
                )
                with open(src_path) as f:
                    assert f.read() == content

    @settings(max_examples=30)
    @given(pairs=rename_pairs)
    def test_history_file_schema(self, pairs):
        """History file has required schema fields."""
        with tempfile.TemporaryDirectory() as d:
            sources = []
            for src_name, dst_name, ext in pairs:
                src_path = os.path.join(d, f"{src_name}{ext}")
                dst_path = os.path.join(d, f"{dst_name}{ext}")
                with open(src_path, "w") as f:
                    f.write("x")
                sources.append((src_path, dst_path))

            journal = build_transaction(sources, run_id="schema-test")
            journal_path = write_journal_atomically(journal, d)
            execute_transaction(journal_path)

            committed = _read_journal(journal_path)
            history_path = write_history_file(committed, d)
            history_data = parse_history_file(history_path)

            # Required fields
            assert "timestamp" in history_data
            assert "run_id" in history_data
            assert "renamed_files" in history_data
            assert history_data["run_id"] == "schema-test"

            # Each entry has original and new
            for entry in history_data["renamed_files"]:
                assert isinstance(entry["original"], str)
                assert isinstance(entry["new"], str)
                assert os.path.isabs(entry["original"])
                assert os.path.isabs(entry["new"])

    @settings(max_examples=30)
    @given(pairs=rename_pairs)
    def test_undo_skips_missing_files(self, pairs):
        """When the 'new' file no longer exists, undo skips it gracefully."""
        with tempfile.TemporaryDirectory() as d:
            sources = []
            for src_name, dst_name, ext in pairs:
                src_path = os.path.join(d, f"{src_name}{ext}")
                dst_path = os.path.join(d, f"{dst_name}{ext}")
                with open(src_path, "w") as f:
                    f.write("x")
                sources.append((src_path, dst_path))

            journal = build_transaction(sources, run_id="test")
            journal_path = write_journal_atomically(journal, d)
            execute_transaction(journal_path)

            committed = _read_journal(journal_path)
            history_path = write_history_file(committed, d)
            history_data = parse_history_file(history_path)

            # Delete all renamed files (simulate user removed them)
            for _, dst_path in sources:
                if os.path.exists(dst_path):
                    os.unlink(dst_path)

            # Undo plan should be empty (all sources missing)
            undo_plan = build_undo_plan(history_data)
            assert len(undo_plan) == 0

    @settings(max_examples=30)
    @given(pairs=rename_pairs)
    def test_undo_handles_conflict_with_suffix(self, pairs):
        """When original path is occupied, undo uses counter suffix."""
        with tempfile.TemporaryDirectory() as d:
            sources = []
            for src_name, dst_name, ext in pairs:
                src_path = os.path.join(d, f"{src_name}{ext}")
                dst_path = os.path.join(d, f"{dst_name}{ext}")
                with open(src_path, "w") as f:
                    f.write("x")
                sources.append((src_path, dst_path))

            journal = build_transaction(sources, run_id="test")
            journal_path = write_journal_atomically(journal, d)
            execute_transaction(journal_path)

            committed = _read_journal(journal_path)
            history_path = write_history_file(committed, d)
            history_data = parse_history_file(history_path)

            # Create files at the original locations (simulate conflict)
            for src_path, _ in sources:
                with open(src_path, "w") as f:
                    f.write("blocker")

            # Undo plan should use counter suffixes
            undo_plan = build_undo_plan(history_data)
            assert len(undo_plan) == len(sources)
            for (src_orig, _), (undo_src, undo_dst) in zip(sources, undo_plan):
                # Destination should NOT be the exact original (it's occupied)
                assert undo_dst != src_orig, (
                    f"Expected counter suffix but got exact original: {undo_dst}"
                )
                # Should be a variant with " (N)" suffix
                base, ext_part = os.path.splitext(src_orig)
                assert undo_dst.startswith(base + " ("), (
                    f"Expected suffix variant of '{src_orig}', got '{undo_dst}'"
                )

    def test_empty_transaction_no_history(self):
        """A transaction with no operations doesn't produce a history file."""
        with tempfile.TemporaryDirectory() as d:
            journal = build_transaction([], run_id="empty")
            # Manually set state as if committed
            for op in journal.operations:
                op.state = "done"
            result = write_history_file(journal, d)
            assert result is None

    def test_parse_invalid_json_raises(self):
        """parse_history_file raises InvalidConfigError for invalid JSON."""
        from tvrenamer.exceptions import InvalidConfigError

        with tempfile.TemporaryDirectory() as d:
            bad_file = os.path.join(d, "bad.json")
            with open(bad_file, "w") as f:
                f.write("not json {{{")

            import pytest
            with pytest.raises(InvalidConfigError):
                parse_history_file(bad_file)

    def test_parse_missing_file_raises(self):
        """parse_history_file raises InvalidConfigError for missing file."""
        from tvrenamer.exceptions import InvalidConfigError
        import pytest

        with pytest.raises(InvalidConfigError):
            parse_history_file("/nonexistent/path/history.json")

    def test_parse_missing_renamed_files_raises(self):
        """parse_history_file raises InvalidConfigError when renamed_files is missing."""
        from tvrenamer.exceptions import InvalidConfigError
        import pytest

        with tempfile.TemporaryDirectory() as d:
            bad_file = os.path.join(d, "bad.json")
            with open(bad_file, "w") as f:
                json.dump({"timestamp": "2025-01-01", "run_id": "x"}, f)

            with pytest.raises(InvalidConfigError):
                parse_history_file(bad_file)
