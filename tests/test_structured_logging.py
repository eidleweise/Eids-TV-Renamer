import json
from tvrenamer.logging_setup import setup_json_logging, set_run_id
from tvrenamer.cache import DiskCache
from tvrenamer.renamer.transaction import build_transaction, write_journal_atomically


def test_structured_logging_includes_run_and_provider(tmp_path):
    logf = tmp_path / "tv.log"
    # initialize JSON logging to file
    setup_json_logging(str(logf), level="DEBUG")
    run_id = "test-run-123"
    set_run_id(run_id)

    cache_path = tmp_path / ".tvcache.json"
    cache = DiskCache(str(cache_path))
    # trigger a cache set log with provider extra
    cache.set("tvmaze", "show:1", {"title": "X"}, extra={"provider": "tvmaze"})

    # write a journal which should log journal write including run_id
    j = build_transaction(
        [(str(tmp_path / "a.mkv"), str(tmp_path / "b.mkv"))], run_id=run_id
    )
    write_journal_atomically(j, str(tmp_path))

    # read log file and parse JSON lines
    assert logf.exists(), "Log file not created"
    with open(str(logf), "r") as f:
        lines = [line.strip() for line in f.readlines() if line.strip()]
    objs = [json.loads(line) for line in lines]

    # assert there's at least one log entry with provider field
    assert any(o.get("fields", {}).get("provider") == "tvmaze" for o in objs), objs
    # assert there's at least one log entry with run_id
    assert any(
        o.get("fields", {}).get("run_id") == run_id
        or o.get("fields", {}).get("run_id") == "test-run-123"
        for o in objs
    ), objs
