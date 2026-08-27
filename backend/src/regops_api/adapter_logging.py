"""Suppress payload-bearing dependency diagnostics only in this call context."""

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock
from typing import Any

_sensitive: ContextVar[bool] = ContextVar("regops_sensitive_adapter", default=False)
_lock = Lock()
_installed = False


class _SensitiveFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        # Runs after Logger.makeRecord adds structured `extra` fields. Dropping
        # the record also protects diagnostics supplied outside msg/args.
        return not _sensitive.get()


_filter = _SensitiveFilter()


@contextmanager
def sensitive_io() -> Iterator[None]:
    global _installed
    with _lock:
        if not _installed:
            previous = logging.getLogRecordFactory()

            def safe_record(*args: Any, **kwargs: Any) -> logging.LogRecord:
                record = previous(*args, **kwargs)
                if _sensitive.get():
                    logging.getLogger(record.name).addFilter(_filter)
                    record.msg = "ADAPTER_DIAGNOSTIC_SUPPRESSED"
                    record.args = ()
                    record.exc_info = None
                    record.exc_text = None
                    record.stack_info = None
                return record

            logging.setLogRecordFactory(safe_record)
            _installed = True
    token = _sensitive.set(True)
    try:
        yield
    finally:
        _sensitive.reset(token)
