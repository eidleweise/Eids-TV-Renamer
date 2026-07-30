import json
import logging
from tvrenamer.logging_setup import setup_json_logging
from tvrenamer.cache import DiskCache


def test_cache_logs_include_provider(tmp_path):
    log_file = tmp_path / "tvrenamer.log"
    setup_json_logging(str(log_file), level="DEBUG")
    cache_path = tmp_path / "cache.json"
    cache = DiskCache(str(cache_path))

    # set and get with provider extra
    cache.set("tvmaze", "k1", {"a": 1}, extra={"provider": "tvmaze"})
    # get should log hit
    val = cache.get("tvmaze", "k1", extra={"provider": "tvmaze"})
    assert val == {"a": 1}

    # flush handlers
    for h in list(logging.getLogger().handlers):
        try:
            h.flush()
        except Exception:
            pass

    text = log_file.read_text()
    lines = [line for line in text.splitlines() if line.strip()]
    assert lines, "No log lines written"
    parsed = [json.loads(line) for line in lines]
    # find any record with fields.provider == 'tvmaze'
    found = any((p.get("fields") or {}).get("provider") == "tvmaze" for p in parsed)
    assert found, f"Provider field not found in logs: {parsed}"
