"""Strip secrets from error text before it is stored or logged."""

from __future__ import annotations

import re

_TOKEN_RE = re.compile(r"\d{8,}:[A-Za-z0-9_-]{20,}")
_BEARER_RE = re.compile(r"(Bearer\s+)[A-Za-z0-9._\-]+", re.IGNORECASE)
_PASSWORD_RE = re.compile(r"(://[^:/@]+:)[^@/]+(@)")
_CARD_RE = re.compile(r"\b\d{13,19}\b")


def sanitize_error(message: str, *, limit: int = 1500) -> str:
    text = _TOKEN_RE.sub("[redacted-token]", message)
    text = _BEARER_RE.sub(r"\1[redacted]", text)
    text = _PASSWORD_RE.sub(r"\1[redacted]\2", text)
    text = _CARD_RE.sub("[redacted-card]", text)
    return text[:limit]
