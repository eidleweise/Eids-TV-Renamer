import json
import logging
from tvrenamer.logging_setup import setup_json_logging


def test_json_logging_and_redaction(tmp_path):
    log_file = tmp_path / "tvrenamer.log"
    # setup JSON logging
    setup_json_logging(str(log_file), level="DEBUG")
    logger = logging.getLogger("test")
    # log a message with a fake API key and structured fields
    logger.info(
        "Calling provider",
        extra={
            "api_key": "SECRET123",
            "token": "abc.def",
            "journal_id": "J1",
            "provider": "tvmaze",
        },
    )
    logger.debug("Debug message without secrets", extra={"journal_id": "J1"})

    # flush handlers
    for h in list(logging.getLogger().handlers):
        h.flush()

    # read log file
    text = log_file.read_text()
    lines = [line for line in text.splitlines() if line.strip()]
    assert len(lines) >= 1
    # parse JSON lines
    parsed = [json.loads(line) for line in lines]
    msgs = [p["message"] for p in parsed]
    # ensure redaction occurred (api_key should be redacted)
    assert any("REDACTED" in m.upper() for m in msgs) or any(
        "REDACTED" in str(p.get("fields", {})) for p in parsed
    )
    assert any("Debug message" in m for m in msgs)
    # ensure structured fields present
    assert any(p.get("fields", {}).get("journal_id") == "J1" for p in parsed)
    assert any(p.get("fields", {}).get("provider") == "tvmaze" for p in parsed)
