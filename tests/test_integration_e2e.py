"""Integration tests for end-to-end CLI scenarios.

Validates: Requirements 7.1-7.7, 10.1-10.8, 11.1-11.7, 15.1-15.6
"""

import json
import os
import subprocess
import tempfile

import pytest


def _run_cli(*args, cwd=None):
    """Run tvrenamer CLI and return (returncode, stdout, stderr)."""
    cmd = ["python", "-m", "tvrenamer.cli"] + list(args)
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=cwd)
    return result.returncode, result.stdout, result.stderr


class TestEndToEndDryRun:
    """Full rename dry-run with temp directory trees."""

    def test_basic_rename_dry_run(self, tmp_path):
        """Dry-run produces preview and exits 0."""
        show_dir = tmp_path / "The.Wire"
        show_dir.mkdir()
        (show_dir / "The.Wire.S01E01.720p.mkv").write_text("v")
        (show_dir / "The.Wire.S01E02.720p.mkv").write_text("v")

        code, stdout, stderr = _run_cli(
            "--path", str(tmp_path), "--no-fetch-titles", "--no-color"
        )
        assert code == 0
        assert "2 file(s) would be renamed" in stdout
        assert "S01E01" in stdout
        assert "S01E02" in stdout

    def test_show_name_cleaned(self, tmp_path):
        """Show name is cleaned from scene tags and title-cased."""
        show_dir = tmp_path / "the.wire.720p.HDTV"
        show_dir.mkdir()
        (show_dir / "the.wire.S01E01.720p.HDTV.mkv").write_text("v")

        code, stdout, _ = _run_cli(
            "--path", str(tmp_path), "--no-fetch-titles", "--no-color"
        )
        assert code == 0
        # Show name should be cleaned and title-cased
        assert "The Wire" in stdout

    def test_season_dir_structure(self, tmp_path):
        """Show/Season N/file.mkv extracts show from grandparent."""
        show_dir = tmp_path / "Breaking Bad" / "Season 1"
        show_dir.mkdir(parents=True)
        (show_dir / "breaking.bad.S01E01.mkv").write_text("v")

        code, stdout, _ = _run_cli(
            "--path", str(tmp_path), "--no-fetch-titles", "--no-color"
        )
        assert code == 0
        assert "Breaking Bad" in stdout


class TestEndToEndExecute:
    """Execute mode with real renames."""

    def test_rename_execute(self, tmp_path):
        """--execute performs actual renames."""
        show_dir = tmp_path / "Show"
        show_dir.mkdir()
        src = show_dir / "Show.S01E01.mkv"
        src.write_text("video")

        code, stdout, _ = _run_cli(
            "--path", str(tmp_path), "--no-fetch-titles", "--execute", "--no-color"
        )
        assert code == 0
        assert "1 file(s) renamed" in stdout
        # Original should be gone
        assert not src.exists()
        # New file should exist
        new_files = list(show_dir.glob("*.mkv"))
        assert len(new_files) == 1
        assert "S01E01" in new_files[0].name

    def test_history_file_created(self, tmp_path):
        """Execute creates a history file."""
        show_dir = tmp_path / "Show"
        show_dir.mkdir()
        (show_dir / "Show.S01E01.mkv").write_text("v")

        code, _, _ = _run_cli(
            "--path", str(tmp_path), "--no-fetch-titles", "--execute", "--no-color"
        )
        assert code == 0
        history_files = list(tmp_path.glob("renamed_history_*.json"))
        assert len(history_files) >= 1

        # Validate history file content
        with open(history_files[0]) as f:
            data = json.load(f)
        assert "timestamp" in data
        assert "run_id" in data
        assert "renamed_files" in data
        assert len(data["renamed_files"]) == 1


class TestEndToEndUndo:
    """Undo round-trip on real filesystem."""

    def test_undo_round_trip(self, tmp_path):
        """Rename then undo restores original file."""
        show_dir = tmp_path / "Show"
        show_dir.mkdir()
        src = show_dir / "Show.S01E01.mkv"
        src.write_text("original content")

        # Execute rename
        code, _, _ = _run_cli(
            "--path", str(tmp_path), "--no-fetch-titles", "--execute", "--no-color"
        )
        assert code == 0
        assert not src.exists()

        # Find history file
        history_files = list(tmp_path.glob("renamed_history_*.json"))
        assert len(history_files) >= 1

        # Execute undo
        code, stdout, _ = _run_cli(
            "--undo", str(history_files[0]), "--execute", "--no-color",
            "--path", str(tmp_path),
        )
        assert code == 0
        assert "restored" in stdout

        # Original file should be back
        assert src.exists()
        assert src.read_text() == "original content"


class TestEndToEndExitCodes:
    """Exit code scenarios."""

    def test_exit_0_success(self, tmp_path):
        show_dir = tmp_path / "Show"
        show_dir.mkdir()
        (show_dir / "Show.S01E01.mkv").write_text("v")

        code, _, _ = _run_cli(
            "--path", str(tmp_path), "--no-fetch-titles", "--no-color"
        )
        assert code == 0

    def test_exit_1_no_media(self, tmp_path):
        """Empty directory returns exit code 1."""
        code, _, stderr = _run_cli("--path", str(tmp_path), "--no-color")
        assert code == 1
        assert "No media files" in stderr

    def test_exit_4_invalid_undo_file(self, tmp_path):
        """Invalid undo file returns exit code 4."""
        code, _, stderr = _run_cli("--undo", "/nonexistent.json", "--path", str(tmp_path))
        assert code == 4

    def test_exit_4_invalid_history_format(self, tmp_path):
        """History file with bad format returns exit code 4."""
        bad = tmp_path / "bad.json"
        bad.write_text('{"not": "valid_history"}')
        code, _, stderr = _run_cli("--undo", str(bad), "--path", str(tmp_path))
        assert code == 4


class TestEndToEndJunkCleanup:
    """Junk cleanup integration."""

    def test_trash_junk(self, tmp_path):
        """--trash-junk moves junk to .trash/."""
        show_dir = tmp_path / "Show"
        show_dir.mkdir()
        (show_dir / "Show.S01E01.mkv").write_text("v")
        (show_dir / "info.nfo").write_text("j")
        (show_dir / "cover.jpg").write_text("j")

        code, stdout, _ = _run_cli(
            "--path", str(tmp_path), "--no-fetch-titles", "--trash-junk", "--no-color"
        )
        assert code == 0
        assert "junk file(s) trashed" in stdout
        trash = show_dir / ".trash"
        assert trash.is_dir()
        assert (trash / "info.nfo").exists()
        assert (trash / "cover.jpg").exists()

    def test_clean_junk(self, tmp_path):
        """--clean-junk permanently deletes junk."""
        show_dir = tmp_path / "Show"
        show_dir.mkdir()
        (show_dir / "Show.S01E01.mkv").write_text("v")
        nfo = show_dir / "info.nfo"
        nfo.write_text("j")

        code, stdout, _ = _run_cli(
            "--path", str(tmp_path), "--no-fetch-titles", "--clean-junk", "--no-color"
        )
        assert code == 0
        assert "junk file(s) deleted" in stdout
        assert not nfo.exists()

    def test_junk_does_not_touch_videos(self, tmp_path):
        """Junk cleanup never touches video files."""
        show_dir = tmp_path / "Show"
        show_dir.mkdir()
        video = show_dir / "Show.S01E01.mkv"
        video.write_text("v")

        code, _, _ = _run_cli(
            "--path", str(tmp_path), "--no-fetch-titles", "--clean-junk", "--no-color"
        )
        assert code == 0
        assert video.exists()


class TestEndToEndVerboseQuiet:
    """Verbose and quiet output modes."""

    def test_verbose_shows_details(self, tmp_path):
        """--verbose prints provider and config details to stderr."""
        show_dir = tmp_path / "Show"
        show_dir.mkdir()
        (show_dir / "Show.S01E01.mkv").write_text("v")

        code, _, stderr = _run_cli(
            "--path", str(tmp_path), "--no-fetch-titles", "--verbose", "--no-color"
        )
        assert code == 0
        assert "Providers:" in stderr or "Template:" in stderr

    def test_quiet_suppresses_output(self, tmp_path):
        """--quiet produces no stdout."""
        show_dir = tmp_path / "Show"
        show_dir.mkdir()
        (show_dir / "Show.S01E01.mkv").write_text("v")

        code, stdout, _ = _run_cli(
            "--path", str(tmp_path), "--no-fetch-titles", "--quiet"
        )
        assert code == 0
        assert stdout.strip() == ""

    def test_quiet_still_shows_errors(self, tmp_path):
        """--quiet still shows errors on stderr."""
        code, _, stderr = _run_cli("--path", str(tmp_path), "--quiet")
        assert code == 1
        assert "No media files" in stderr


class TestEndToEndExclude:
    """Exclude patterns integration."""

    def test_exclude_filters_files(self, tmp_path):
        """--exclude removes matching files from plan."""
        show_dir = tmp_path / "Show"
        show_dir.mkdir()
        (show_dir / "Show.S01E01.mkv").write_text("v")
        (show_dir / "Show.S01E02.sample.mkv").write_text("v")

        code, stdout, _ = _run_cli(
            "--path", str(tmp_path), "--no-fetch-titles", "--no-color",
            "--exclude", "*sample*",
        )
        assert code == 0
        assert "1 file(s) would be renamed" in stdout

    def test_multiple_exclude_patterns(self, tmp_path):
        """Multiple --exclude flags combine as union."""
        show_dir = tmp_path / "Show"
        show_dir.mkdir()
        (show_dir / "Show.S01E01.mkv").write_text("v")
        (show_dir / "Show.S01E02.sample.mkv").write_text("v")
        (show_dir / "Show.S01E03.extra.mkv").write_text("v")

        code, stdout, _ = _run_cli(
            "--path", str(tmp_path), "--no-fetch-titles", "--no-color",
            "--exclude", "*sample*", "--exclude", "*extra*",
        )
        assert code == 0
        assert "1 file(s) would be renamed" in stdout
