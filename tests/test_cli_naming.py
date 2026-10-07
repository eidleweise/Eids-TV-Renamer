"""CLI-level tests for Part B interactive manual naming.

These follow tests/test_crash_recovery.py: they drive main([...]) and patch
builtins.input. The provider seam is monkeypatched via
tvrenamer.cli.build_providers_from_config (cli.py imports it into its own
namespace), returning a controllable DummyProvider list — NOT --providers dummy,
which resolves to an empty provider list.

Per the design's prompt-cascade requirement, every interactive test PINS all
non-naming wizard options via CLI flags and runs against a tree with NO pending
journal, so the only input() calls left are the naming prompts.
"""

import os

from unittest.mock import patch

from tvrenamer.cli import main
from tests.helpers import DummyProvider


# Pinned template/options shared by the interactive tests so the only prompts
# that can fire are the naming prompts.
_TEMPLATE = "{show} - S{season}E{episode} - {title}{ext}"


def _make_tree(tmp_path, dir_name="Dirty Name", fname="Dirty.Name.S01E01.1080p.mkv"):
    """Create a single-show tree whose cleaned title is 'Dirty Name'."""
    show_dir = tmp_path / dir_name
    show_dir.mkdir()
    (show_dir / fname).write_text("video")
    return show_dir


def _pin_flags(tmp_path):
    """Non-naming wizard options pinned via flags (dry-run form)."""
    return [
        "--path", str(tmp_path),
        "--interactive",
        "--providers", "tvmaze",
        "--execute",
        "--fetch-titles",
        "--template", _TEMPLATE,
        "--space-replacement", "none",
        "--no-color",
    ]


def test_wrong_then_correct_name_adopted(tmp_path, monkeypatch):
    """A wrong name re-prompts; the correct name is identified and adopted
    for both the destination filename and the title lookup."""
    _make_tree(tmp_path)
    rec = []
    # Miss on the cleaned "Dirty Name" (opens the loop) and on "WrongName"
    # (re-prompts); hit on "CorrectName".
    dummy = DummyProvider(unidentified=["Dirty Name", "WrongName"], record=rec)
    monkeypatch.setattr(
        "tvrenamer.cli.build_providers_from_config", lambda *a, **k: [dummy]
    )
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    with patch("builtins.input", side_effect=["WrongName", "CorrectName"]):
        result = main(_pin_flags(tmp_path))

    assert result == 0
    # The resolved name reached get_episode_title.
    assert "CorrectName" in rec
    assert "Dirty Name" not in rec
    assert "WrongName" not in rec
    # The executed rename used CorrectName in the destination filename.
    renamed = [
        f for f in os.listdir(tmp_path / "Dirty Name")
        if f.startswith("CorrectName - S01E01")
    ]
    assert renamed, os.listdir(tmp_path / "Dirty Name")


def test_non_interactive_never_prompts(tmp_path, monkeypatch):
    """Without --interactive, no resolver is built, so input() is never called
    and the cleaned name is used."""
    _make_tree(tmp_path)
    rec = []
    dummy = DummyProvider(unidentified=["Dirty Name"], record=rec)
    monkeypatch.setattr(
        "tvrenamer.cli.build_providers_from_config", lambda *a, **k: [dummy]
    )

    def _no_input(*a, **k):
        raise AssertionError("input() must not be called in non-interactive mode")

    with patch("builtins.input", side_effect=_no_input):
        result = main([
            "--path", str(tmp_path),
            "--fetch-titles",
            "--template", _TEMPLATE,
            "--space-replacement", "none",
            "--no-color",
        ])

    assert result == 0
    # Cleaned name used (never prompted, so no correction).
    assert "Dirty Name" in rec


def test_no_interactive_naming_opt_out(tmp_path, monkeypatch):
    """--no-interactive-naming suppresses only the naming prompts even in the
    interactive wizard; the cleaned name is used and input() is never called."""
    _make_tree(tmp_path)
    rec = []
    dummy = DummyProvider(unidentified=["Dirty Name"], record=rec)
    monkeypatch.setattr(
        "tvrenamer.cli.build_providers_from_config", lambda *a, **k: [dummy]
    )
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    def _no_input(*a, **k):
        raise AssertionError("input() must not be called with --no-interactive-naming")

    with patch("builtins.input", side_effect=_no_input):
        result = main(_pin_flags(tmp_path) + ["--no-interactive-naming"])

    assert result == 0
    assert "Dirty Name" in rec


def test_eof_at_naming_prompt_skips(tmp_path, monkeypatch):
    """EOF at the naming prompt skips (keeps the cleaned name); no crash."""
    _make_tree(tmp_path)
    rec = []
    dummy = DummyProvider(unidentified=["Dirty Name"], record=rec)
    monkeypatch.setattr(
        "tvrenamer.cli.build_providers_from_config", lambda *a, **k: [dummy]
    )
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    with patch("builtins.input", side_effect=EOFError):
        result = main(_pin_flags(tmp_path))

    assert result == 0
    # Skipped → cleaned name used.
    assert "Dirty Name" in rec
