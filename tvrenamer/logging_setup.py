import logging
import json
import re
from logging.handlers import RotatingFileHandler
from typing import Optional

SENSITIVE_PATTERNS = [
    re.compile(r'(?i)(api[_-]?key)\s*[=:]\s*"?\w+"?'),
    re.compile(r'(?i)(token)\s*[=:]\s*"?\S+"?'),
    re.compile(r'(?i)(password)\s*[=:]\s*"?\S+"?'),
]

# Standard logging record attributes — used to filter out extras in formatters
_STANDARD_LOG_ATTRS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "taskName", "task",
}

_SENSITIVE_KEYS = {"api_key", "apikey", "token", "password", "secret"}

# run-level correlation id
CURRENT_RUN_ID: Optional[str] = None


def set_run_id(run_id: Optional[str]):
    global CURRENT_RUN_ID
    CURRENT_RUN_ID = run_id


def _redact_text(text: str) -> str:
    if not text:
        return text
    t = text
    for p in SENSITIVE_PATTERNS:
        t = p.sub(lambda m: f"{m.group(1)}=REDACTED", t)
    # common JSON-like patterns: "api_key":"..."
    t = re.sub(r"(?i)(\"?(api[_-]?key)\"?\s*:\s*\").*?(\")", r"\1REDACTED\3", t)
    return t


class JSONFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        msg = getattr(record, "_redacted_msg", None) or _redact_text(record.getMessage())
        payload = {
            "timestamp": self.formatTime(record, self.datefmt),
            "level": record.levelname,
            "logger": record.name,
            "message": msg,
        }
        # include extra dynamic fields from the record that are not standard
        extras = {}
        for k, v in record.__dict__.items():
            if k in _STANDARD_LOG_ATTRS:
                continue
            # skip internal attributes
            if k.startswith("_"):
                continue
            # redact by key name
            if k.lower() in _SENSITIVE_KEYS:
                extras[k] = "REDACTED"
                continue
            # redact string values
            if isinstance(v, str):
                try:
                    rv = _redact_text(v)
                except Exception:
                    rv = v
                extras[k] = rv
            else:
                try:
                    json.dumps({k: v})
                    extras[k] = v
                except Exception:
                    extras[k] = str(v)
        if extras:
            payload["fields"] = extras
        # inject global run id if present
        if CURRENT_RUN_ID:
            payload.setdefault("fields", {})
            payload["fields"]["run_id"] = CURRENT_RUN_ID
        return json.dumps(payload, ensure_ascii=False)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Create a redacted copy of the message without mutating the original record.
        # We set a private attribute that formatters can use instead of record.msg.
        try:
            original_msg = record.getMessage()
            record._redacted_msg = _redact_text(original_msg)
        except Exception:
            record._redacted_msg = None
        return True


def setup_json_logging(
    log_file: Optional[str] = None,
    level: str = "INFO",
    max_bytes: int = 10 * 1024 * 1024,
    backup_count: int = 3,
):
    # remove existing handlers
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    lvl = getattr(logging, level.upper(), logging.INFO)
    formatter = JSONFormatter()
    filter_ = RedactingFilter()

    # console handler (human friendly)
    class ConsoleFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            # base message (use redacted version if available)
            redacted = getattr(record, "_redacted_msg", None) or record.getMessage()
            msg = f"{record.levelname}: {redacted}"
            # collect non-standard extras to display concisely
            extras_parts = []
            for k, v in record.__dict__.items():
                if k in _STANDARD_LOG_ATTRS or k.startswith("_"):
                    continue
                # redact sensitive keys
                if k.lower() in _SENSITIVE_KEYS:
                    extras_parts.append(f"{k}=REDACTED")
                    continue
                # skip None values (noisy)
                if v is None:
                    continue
                # show short repr
                try:
                    if isinstance(v, str):
                        extras_parts.append(f"{k}={_redact_text(v)}")
                    else:
                        extras_parts.append(f"{k}={v!r}")
                except Exception:
                    extras_parts.append(f"{k}=<unserializable>")
            if extras_parts:
                msg = msg + " | " + ", ".join(extras_parts)
            return msg

    ch = logging.StreamHandler()
    ch.setLevel(lvl)
    ch.setFormatter(ConsoleFormatter())
    ch.addFilter(filter_)
    root.addHandler(ch)

    if log_file:
        # rotating file handler with JSON formatter
        fh = RotatingFileHandler(log_file, maxBytes=max_bytes, backupCount=backup_count)
        fh.setLevel(lvl)
        fh.setFormatter(formatter)
        fh.addFilter(filter_)
        root.addHandler(fh)

    root.setLevel(lvl)
