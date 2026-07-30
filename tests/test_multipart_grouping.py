import os
from tvrenamer.renamer.engine import plan_renames
from tests.helpers import DummyProvider


def test_grouped_parts_are_numbered(tmp_path):
    show_dir = tmp_path / "Show"
    show_dir.mkdir()
    f1 = show_dir / "Show.S01E05.part1.mkv"
    f1.write_text("a")
    f2 = show_dir / "Show.S01E05.part2.mkv"
    f2.write_text("b")

    providers = [DummyProvider()]
    plan = plan_renames(str(tmp_path), providers=providers)
    basenames = [os.path.basename(dst) for _, dst in plan]

    assert any("S01E05" in b and "Part 1" in b for b in basenames)
    assert any("S01E05" in b and "Part 2" in b for b in basenames)
