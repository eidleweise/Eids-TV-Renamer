import os
from tvrenamer.renamer.engine import plan_renames
from tests.helpers import DummyProvider


def test_episode_range_and_part_detection(tmp_path):
    # setup directories and files
    show_dir = tmp_path / "My.Show"
    show_dir.mkdir()
    f1 = show_dir / "My.Show.S01E01-02.mkv"
    f1.write_text("x")
    f2 = show_dir / "My.Show - S01E03 - part1.mkv"
    f2.write_text("y")

    providers = [DummyProvider()]
    plan = plan_renames(str(tmp_path), providers=providers)
    basenames = [os.path.basename(dst) for _, dst in plan]

    # expect episode token to be 01-02 (allow en-dash) and 03 without a part suffix when it's a single file
    import re

    assert any(re.search(r"S01E01[-–]02", b) for b in basenames), basenames
    # single-file part1 should not show part suffix
    assert any("S01E03" in b and "Part 1" not in b for b in basenames), basenames
