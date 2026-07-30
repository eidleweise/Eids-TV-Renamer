import os
from tvrenamer.renamer.engine import plan_renames, perform_transaction_for_plan


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
