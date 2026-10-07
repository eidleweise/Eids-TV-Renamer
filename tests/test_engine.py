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


# --- Part B: name_resolver seam ---


def _make_show_tree(tmp_path, dir_name="Dirty Name", fname="Dirty.Name.S01E01.1080p.mkv"):
    """Create a single-show tree and return the show directory path."""
    show_dir = tmp_path / dir_name
    show_dir.mkdir()
    (show_dir / fname).write_text("video")
    return show_dir


def test_name_resolver_corrected_name_adopted_end_to_end(tmp_path):
    """A corrected name flows into BOTH the destination filename and the
    get_episode_title lookup."""
    _make_show_tree(tmp_path)
    rec = []
    providers = [DummyProvider(record=rec)]
    plan = plan_renames(
        str(tmp_path),
        providers=providers,
        name_resolver=lambda show, year: "Correct Show",
    )
    assert len(plan) == 1
    _, dst = plan[0]
    assert os.path.basename(dst).startswith("Correct Show - S01E01")
    # The resolved name reached the title lookup, not the cleaned "Dirty Name".
    assert "Correct Show" in rec
    assert "Dirty Name" not in rec


def test_name_resolver_identity_passes_through_unchanged(tmp_path):
    """An identity resolver yields the same result as no override."""
    _make_show_tree(tmp_path)
    providers = [DummyProvider()]
    plan = plan_renames(
        str(tmp_path),
        providers=providers,
        name_resolver=lambda show, year: show,
    )
    assert len(plan) == 1
    _, dst = plan[0]
    assert os.path.basename(dst).startswith("Dirty Name - S01E01")


def test_no_name_resolver_is_unchanged_behavior(tmp_path):
    """With no resolver (the default), the plan matches today's output exactly."""
    _make_show_tree(tmp_path)
    providers_a = [DummyProvider()]
    providers_b = [DummyProvider()]
    plan_default = plan_renames(str(tmp_path), providers=providers_a)
    plan_explicit_none = plan_renames(
        str(tmp_path), providers=providers_b, name_resolver=None
    )
    assert plan_default == plan_explicit_none
    assert len(plan_default) == 1
    _, dst = plan_default[0]
    assert os.path.basename(dst).startswith("Dirty Name - S01E01")


def test_name_resolver_called_once_per_distinct_show(tmp_path):
    """The resolver is invoked at most once per distinct cleaned show name."""
    # One show, several episodes → exactly one resolver call.
    show_dir = tmp_path / "Dirty Name"
    show_dir.mkdir()
    for ep in ("S01E01", "S01E02", "S01E03"):
        (show_dir / f"Dirty.Name.{ep}.1080p.mkv").write_text("video")

    calls = []

    def resolver(show, year):
        calls.append(show)
        return show

    plan_renames(str(tmp_path), providers=[DummyProvider()], name_resolver=resolver)
    assert len(calls) == 1

    # Add a second distinct show → two calls total for a fresh scan.
    other_dir = tmp_path / "Another Show"
    other_dir.mkdir()
    (other_dir / "Another.Show.S02E01.1080p.mkv").write_text("video")

    calls2 = []

    def resolver2(show, year):
        calls2.append(show)
        return show

    plan_renames(str(tmp_path), providers=[DummyProvider()], name_resolver=resolver2)
    assert len(calls2) == 2
    assert set(calls2) == {"Dirty Name", "Another Show"}


def test_name_resolver_exception_is_swallowed(tmp_path):
    """A resolver that raises does not crash planning; the cleaned name is kept."""
    _make_show_tree(tmp_path)

    def boom(show, year):
        raise RuntimeError("resolver blew up")

    plan = plan_renames(
        str(tmp_path), providers=[DummyProvider()], name_resolver=boom
    )
    assert len(plan) == 1
    _, dst = plan[0]
    assert os.path.basename(dst).startswith("Dirty Name - S01E01")
