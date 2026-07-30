import uuid
import json
import os
from tvrenamer.logging_setup import set_run_id
from tvrenamer.renamer.engine import perform_transaction_for_plan


def test_journal_contains_run_id(tmp_path):
    # set a known run_id and ensure it's propagated into the written journal JSON
    run_id = uuid.uuid4().hex
    set_run_id(run_id)

    root = tmp_path
    # create a dummy source file
    src_file = root / "Show.S01E01.mkv"
    src_file.write_text("dummy")
    dst = root / "Show - S01E01 - Episode 01.mkv"
    plan = [(str(src_file), str(dst))]

    journal_path, _ = perform_transaction_for_plan(
        str(root), plan, execute=False, journal_dir=str(root)
    )
    assert os.path.exists(journal_path), "Journal file was not created"

    with open(journal_path, "r") as f:
        data = json.load(f)

    assert "run_id" in data, "run_id missing from journal"
    assert data["run_id"] == run_id
