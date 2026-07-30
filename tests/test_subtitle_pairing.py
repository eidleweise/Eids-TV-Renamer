import os
from tvrenamer.renamer.engine import plan_renames
from tests.helpers import DummyProvider


def test_subtitle_pairs_with_language_and_part(tmp_path):
    show_dir = tmp_path / "Show"
    show_dir.mkdir()
    v1 = show_dir / "Show.S01E05.part1.mkv"
    v1.write_text("v1")
    v2 = show_dir / "Show.S01E05.part2.mkv"
    v2.write_text("v2")
    # subtitles with language suffix and without
    s1 = show_dir / "Show.S01E05.part1.en.srt"
    s1.write_text("s1")
    s2 = show_dir / "Show.S01E05.part2.srt"
    s2.write_text("s2")

    providers = [DummyProvider()]
    plan = plan_renames(str(tmp_path), providers=providers)
    # find subtitle mappings
    sub_mappings = {
        os.path.basename(src): os.path.basename(dst)
        for src, dst in plan
        if os.path.splitext(src)[1] == ".srt"
    }
    assert "Show.S01E05.part1.en.srt" in sub_mappings
    assert any("Part 1" in d for d in sub_mappings.values())
    assert "Show.S01E05.part2.srt" in sub_mappings
    assert any("Part 2" in d for d in sub_mappings.values())
