import os
import pytest
from tvrenamer.renamer.engine import (
    plan_renames,
    perform_transaction_for_plan,
    _truncate_at_se_marker,
)
from tests.helpers import DummyProvider


def test_engine_plan_and_execute(tmp_path):
    show_dir = tmp_path / "My.Show"
    season_dir = show_dir / "Season 01"
    season_dir.mkdir(parents=True)
    f = season_dir / "My.Show.S01E01.1080p.mkv"
    f.write_text("video")

    plan = plan_renames(str(tmp_path))
    assert len(plan) == 1
    src, dst = plan[0]
    assert "S01E01" in os.path.basename(dst)

    # do transaction
    journal_path, plan_out = perform_transaction_for_plan(
        str(tmp_path), plan, execute=True
    )
    # file should have moved
    assert not os.path.exists(src)
    assert os.path.exists(dst)

    # journal should exist
    assert os.path.exists(journal_path)


@pytest.mark.parametrize(
    "name, expected",
    [
        # The user's exact example (post-_strip_scene_tags normalization)
        ("My Show S01 COMPLETE DSNP WEB DL DDP5 1 Atmos H 264", "My Show"),
        # SxxExx marker
        ("My Show S01E05", "My Show"),
        # NxNN marker
        ("My Show 1x01", "My Show"),
        # "Season NN" word form
        ("Show Season 08", "Show"),
        # Multiple words before the marker
        ("The Great Big Adventure S03E12", "The Great Big Adventure"),
        # No marker — unchanged
        ("Breaking Bad", "Breaking Bad"),
        ("The Wire", "The Wire"),
        # Title-leading capital tokens preserved; cut at the real marker,
        # not at the bare leading letters (S.W.A.T. normalizes to "S W A T")
        ("S W A T S01E05", "S W A T"),
        # Truncation would be empty → graceful fallback to the original
        ("S01", "S01"),
    ],
)
def test_truncate_at_se_marker(name, expected):
    assert _truncate_at_se_marker(name) == expected


def test_show_name_truncated_end_to_end(tmp_path):
    show_dir = tmp_path / "My.Show.S01.COMPLETE.1080p.DSNP.WEB-DL.DDP5.1.Atmos.H.264-FLUX[TGx]"
    show_dir.mkdir()
    f = show_dir / "My.Show.S01E01.1080p.mkv"
    f.write_text("video")

    providers = [DummyProvider()]
    plan = plan_renames(str(tmp_path), providers=providers)
    assert len(plan) == 1
    _, dst = plan[0]
    assert os.path.basename(dst).startswith("My Show - S01E01")
