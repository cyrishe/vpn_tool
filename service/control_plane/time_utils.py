from __future__ import annotations

from datetime import UTC, datetime


def utcnow() -> datetime:
    """Return naive UTC for consistent SQLite comparisons."""
    return datetime.now(UTC).replace(tzinfo=None)

