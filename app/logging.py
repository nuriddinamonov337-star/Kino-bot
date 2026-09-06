"""Central logging configuration without printing secrets."""

from __future__ import annotations

import logging

from app.utils.sanitize import sanitize_error


class SecretRedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = sanitize_error(record.msg, limit=4000)
        if record.args:
            record.args = tuple(
                sanitize_error(arg, limit=4000) if isinstance(arg, str) else arg for arg in record.args
            )
        return True


def configure_logging(level: str) -> None:
    logging.basicConfig(
        level=level.upper(),
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
        force=True,
    )
    redactor = SecretRedactingFilter()
    for handler in logging.getLogger().handlers:
        handler.addFilter(redactor)
