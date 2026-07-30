"""Unit tests for crash recovery prompts (Requirement 19).

Tests cover:
- No pending journals → no prompt/warning
- Non-interactive mode with pending journals → warning + proceed
- Interactive mode: resume choice
- Interactive mode: rollback choice
- Interactive mode: ignore choice
- Per-journal failure handling (log, skip, continue)
"""

import json
import os
import tempfile
from unittest.mock import patch
from io import StringIO

import pytest

from tvrenamer.cli import main, find_journals, _handle_pending_journals


def _create_pending_journal(directory, journal_id="test-journal-1", operations=None):
    """Helper to create a pending transaction journal file."""
    if operations is None:
        operations = []
    journal = {
        "version": 1,
        "journal_id": journal_id,
        "timestamp": 1000.0,
        "operations": operations,
        "state": "pending",
        "run_id": "old-run",
    }
    path = os.path.join(directory, f"transaction_{journal_id}.json")
    with open(path, "w") as f:
        json.dump(journal, f)
    return path


def _create_video_file(directory, name="Show.S01E01.mkv"):
    """Helper to create a video file for testing."""
    show_dir = os.path.join(directory, "Show")
    os.makedirs(show_dir, exist_ok=True)
    path = os.path.join(show_dir, name)
    with open(path, "w") as f:
        f.write("video")
    return path


class TestFindJournals:
    def test_finds_pending_journals(self, tmp_path):
        _create_pending_journal(str(tmp_path), "j1")
        _create_pending_journal(str(tmp_path), "j2")
        result = find_journals(str(tmp_path), states=["pending"])
        assert len(result) == 2

    def test_ignores_committed_journals(self, tmp_path):
        # Create a committed journal
        journal = {
            "version": 1, "journal_id": "committed-1",
            "timestamp": 1000.0, "operations": [],
            "state": "committed", "run_id": "old",
        }
        path = tmp_path / "transaction_committed-1.json"
        path.write_text(json.dumps(journal))

        result = find_journals(str(tmp_path), states=["pending"])
        assert len(result) == 0

    def test_empty_directory_returns_empty(self, tmp_path):
        result = find_journals(str(tmp_path), states=["pending"])
        assert result == []


class TestCrashRecoveryNonInteractive:
    def test_no_journals_no_output(self, tmp_path):
        """No pending journals → proceed silently."""
        _create_video_file(str(tmp_path))
        result = main(["--path", str(tmp_path), "--no-fetch-titles", "--no-color"])
        assert result == 0

    def test_pending_journals_warning_to_stderr(self, tmp_path, capsys):
        """Non-interactive mode: prints warning about pending journals."""
        _create_video_file(str(tmp_path))
        _create_pending_journal(str(tmp_path))

        result = main(["--path", str(tmp_path), "--no-fetch-titles", "--no-color"])
        assert result == 0
        captured = capsys.readouterr()
        assert "pending journal" in captured.err.lower()
        assert "--resume" in captured.err or "--rollback" in captured.err

    def test_pending_journals_still_proceeds(self, tmp_path, capsys):
        """Non-interactive mode: proceeds with rename plan despite pending journals."""
        _create_video_file(str(tmp_path))
        _create_pending_journal(str(tmp_path))

        result = main(["--path", str(tmp_path), "--no-fetch-titles", "--no-color"])
        assert result == 0
        captured = capsys.readouterr()
        assert "would be renamed" in captured.out

    def test_quiet_suppresses_warning_stdout(self, tmp_path, capsys):
        """With --quiet, no stdout output even with pending journals."""
        _create_video_file(str(tmp_path))
        _create_pending_journal(str(tmp_path))

        result = main(["--path", str(tmp_path), "--no-fetch-titles", "--quiet"])
        assert result == 0
        captured = capsys.readouterr()
        assert captured.out.strip() == ""


class TestCrashRecoveryInteractive:
    def test_ignore_leaves_journals_and_proceeds(self, tmp_path, capsys):
        """Interactive 'ignore' leaves journals unchanged and proceeds."""
        _create_video_file(str(tmp_path))
        journal_path = _create_pending_journal(str(tmp_path))

        with patch("builtins.input", return_value="i"):
            result = main([
                "--path", str(tmp_path), "--no-fetch-titles",
                "--no-color", "--interactive",
            ])

        assert result == 0
        # Journal should still be pending
        with open(journal_path) as f:
            data = json.load(f)
        assert data["state"] == "pending"
        # Should still show rename preview
        captured = capsys.readouterr()
        assert "would be renamed" in captured.out

    def test_resume_executes_journals(self, tmp_path, capsys):
        """Interactive 'resume' executes pending journals oldest-first."""
        # Create a real pending journal with an actual file to rename
        src = os.path.join(str(tmp_path), "old_file.mkv")
        dst = os.path.join(str(tmp_path), "new_file.mkv")
        with open(src, "w") as f:
            f.write("content")

        journal = {
            "version": 1,
            "journal_id": "resume-test",
            "timestamp": 1000.0,
            "operations": [
                {"id": "op1", "src": src, "dst": dst, "temp": None,
                 "checksum": None, "state": "pending"}
            ],
            "state": "pending",
            "run_id": "old-run",
        }
        j_path = os.path.join(str(tmp_path), "transaction_resume-test.json")
        with open(j_path, "w") as f:
            json.dump(journal, f)

        # Also create a video file so the main flow doesn't fail
        _create_video_file(str(tmp_path))

        with patch("builtins.input", return_value="r"):
            result = main([
                "--path", str(tmp_path), "--no-fetch-titles",
                "--no-color", "--interactive",
            ])

        assert result == 0
        # The journal should have been executed
        assert os.path.exists(dst)
        assert not os.path.exists(src)

    def test_rollback_rolls_back_journals(self, tmp_path, capsys):
        """Interactive 'rollback' rolls back pending journals newest-first."""
        # Create a journal that already has a done operation (simulating interrupted)
        src = os.path.join(str(tmp_path), "original.mkv")
        dst = os.path.join(str(tmp_path), "renamed.mkv")
        # The file is at 'dst' (rename was done)
        with open(dst, "w") as f:
            f.write("content")

        journal = {
            "version": 1,
            "journal_id": "rollback-test",
            "timestamp": 1000.0,
            "operations": [
                {"id": "op1", "src": src, "dst": dst, "temp": None,
                 "checksum": None, "state": "done"}
            ],
            "state": "pending",
            "run_id": "old-run",
        }
        j_path = os.path.join(str(tmp_path), "transaction_rollback-test.json")
        with open(j_path, "w") as f:
            json.dump(journal, f)

        _create_video_file(str(tmp_path))

        with patch("builtins.input", return_value="b"):
            result = main([
                "--path", str(tmp_path), "--no-fetch-titles",
                "--no-color", "--interactive",
            ])

        assert result == 0
        # File should be back at original location
        assert os.path.exists(src)
        assert not os.path.exists(dst)

    def test_eof_on_input_defaults_to_ignore(self, tmp_path, capsys):
        """EOFError on input defaults to ignore behavior."""
        _create_video_file(str(tmp_path))
        _create_pending_journal(str(tmp_path))

        with patch("builtins.input", side_effect=EOFError):
            result = main([
                "--path", str(tmp_path), "--no-fetch-titles",
                "--no-color", "--interactive",
            ])

        assert result == 0
        captured = capsys.readouterr()
        assert "would be renamed" in captured.out


class TestCrashRecoveryFailureHandling:
    def test_failed_resume_logs_and_continues(self, tmp_path, capsys):
        """If a journal fails to resume, log error and continue with run."""
        _create_video_file(str(tmp_path))
        # Create a journal that will fail (source doesn't exist)
        journal = {
            "version": 1,
            "journal_id": "bad-journal",
            "timestamp": 1000.0,
            "operations": [
                {"id": "op1", "src": "/nonexistent/file.mkv",
                 "dst": os.path.join(str(tmp_path), "out.mkv"),
                 "temp": None, "checksum": None, "state": "pending"}
            ],
            "state": "pending",
            "run_id": "old-run",
        }
        j_path = os.path.join(str(tmp_path), "transaction_bad-journal.json")
        with open(j_path, "w") as f:
            json.dump(journal, f)

        with patch("builtins.input", return_value="r"):
            result = main([
                "--path", str(tmp_path), "--no-fetch-titles",
                "--no-color", "--interactive",
            ])

        # Should still succeed overall (graceful failure handling)
        assert result == 0
        captured = capsys.readouterr()
        # Should still proceed with rename preview
        assert "would be renamed" in captured.out

    def test_multiple_journals_handled_independently(self, tmp_path, capsys):
        """Multiple pending journals: each handled independently."""
        _create_video_file(str(tmp_path))

        # Journal 1: will fail (bad source)
        j1 = {
            "version": 1, "journal_id": "j1", "timestamp": 1000.0,
            "operations": [
                {"id": "op1", "src": "/nonexistent.mkv",
                 "dst": os.path.join(str(tmp_path), "out1.mkv"),
                 "temp": None, "checksum": None, "state": "pending"}
            ],
            "state": "pending", "run_id": "r1",
        }
        with open(os.path.join(str(tmp_path), "transaction_j1.json"), "w") as f:
            json.dump(j1, f)

        # Journal 2: empty operations (will succeed trivially)
        j2 = {
            "version": 1, "journal_id": "j2", "timestamp": 2000.0,
            "operations": [],
            "state": "pending", "run_id": "r2",
        }
        with open(os.path.join(str(tmp_path), "transaction_j2.json"), "w") as f:
            json.dump(j2, f)

        with patch("builtins.input", return_value="i"):
            result = main([
                "--path", str(tmp_path), "--no-fetch-titles",
                "--no-color", "--interactive",
            ])

        assert result == 0
        captured = capsys.readouterr()
        # Should mention 2 journals detected
        assert "2" in captured.err
