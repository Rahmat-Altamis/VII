"""Structured logging. API keys are never logged (see redact())."""
from __future__ import annotations

import logging
import re
import sys

_KEY_RE = re.compile(r"(?i)(api[_-]?key|bearer|token)\s*[:=]\s*([\"']?)([^\s\"',}]+)\2")


def redact(text: str) -> str:
    return _KEY_RE.sub(r"\1=***REDACTED***", text)


class _RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            try:
                record.args = tuple(redact(str(a)) for a in record.args)  # type: ignore[union-attr]
            except TypeError:
                pass
        return True


_configured = False


def setup_logging(level: str = "INFO") -> logging.Logger:
    global _configured
    logger = logging.getLogger("vii")
    if not _configured:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
        logger.addHandler(handler)
        logger.addFilter(_RedactingFilter())
        logger.setLevel(getattr(logging, level.upper(), logging.INFO))
        _configured = True
    return logger


log = setup_logging()
