"""Structured logging. API keys are never logged (see redact())."""
from __future__ import annotations

import logging
import re
import sys

_BEARER_RE = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9\-._~+/=]+")
_KV_RE = re.compile(
    r"(?i)(api[_-]?key|access[_-]?token|token|secret|password)\s*[:=]\s*"
    r"([\"']?)([^\s\"',}]+)\2")
_SK_RE = re.compile(r"sk-[A-Za-z0-9\-_]{8,}")


def redact(text: str) -> str:
    text = _BEARER_RE.sub(r"\1***REDACTED***", text)
    text = _KV_RE.sub(r"\1=***REDACTED***", text)
    return _SK_RE.sub("***REDACTED***", text)


class _RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact(record.msg)
        if record.args:
            try:
                record.args = tuple(
                    redact(a) if isinstance(a, str) else a
                    for a in record.args)
            except TypeError:
                pass
        return True


_configured = False


def setup_logging(level: str = "INFO") -> logging.Logger:
    global _configured
    logger = logging.getLogger("vii")
    if not _configured:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"))
        # Handler-level (not only logger-level): records from child
        # loggers (vii.meta, vii.pipeline, ...) propagate to this handler
        # without passing the parent logger's filters.
        handler.addFilter(_RedactingFilter())
        logger.addHandler(handler)
        logger.addFilter(_RedactingFilter())
        logger.setLevel(getattr(logging, level.upper(), logging.INFO))
        _configured = True
    return logger


log = setup_logging()
