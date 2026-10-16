"""Source interface and shared normalization helpers."""

from __future__ import annotations

import logging
import re
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Any, Iterator, Optional

from ..models import JobRecord

log = logging.getLogger(__name__)

_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")

# Tokens that indicate a remote role when found in location/workplace text.
_REMOTE_HINTS = ("remote", "anywhere", "work from home", "wfh", "distributed")


def now_utc_iso() -> str:
    """Current UTC time as an ISO-8601 string."""
    return datetime.now(timezone.utc).isoformat()


def to_iso(value: Any) -> Optional[str]:
    """Best-effort conversion of a date/datetime/epoch/string to ISO-8601.

    Returns None when the value is empty or unparseable.
    """
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        # Heuristic: treat very large numbers as epoch milliseconds.
        secs = value / 1000.0 if value > 1e12 else float(value)
        try:
            return datetime.fromtimestamp(secs, tz=timezone.utc).isoformat()
        except (OverflowError, OSError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        normalized = text.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized).isoformat()
        except ValueError:
            # Keep the raw string rather than losing information.
            return text
    return None


def clean_html(value: Optional[str]) -> Optional[str]:
    """Strip HTML tags and collapse whitespace. Returns None if empty."""
    if not value:
        return None
    text = _TAG_RE.sub(" ", value)
    text = (
        text.replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&nbsp;", " ")
        .replace("&#39;", "'")
        .replace("&quot;", '"')
    )
    text = _WS_RE.sub(" ", text).strip()
    return text or None


def guess_remote(*fields: Any) -> Optional[bool]:
    """Derive a best-effort remote flag from location/workplace text.

    Returns None when no signal is present.
    """
    found_signal = False
    for field in fields:
        if field is None:
            continue
        if isinstance(field, bool):
            return field
        text = str(field).lower()
        if not text:
            continue
        found_signal = True
        if any(hint in text for hint in _REMOTE_HINTS):
            return True
    return False if found_signal else None


class Source(ABC):
    """Common interface every source implements."""

    name: str = "base"

    @abstractmethod
    def fetch(self) -> Iterator[JobRecord]:
        """Yield normalized JobRecords for this source."""
        raise NotImplementedError

    # Shared record factory: enforces url presence and stamps fetched_at.
    def build_record(self, url: Optional[str], **fields: Any) -> Optional[JobRecord]:
        if not url:
            log.warning("[%s] skipping posting with no url", self.name)
            return None
        return JobRecord(
            url=url,
            source=self.name,
            fetched_at=now_utc_iso(),
            title=fields.get("title"),
            company=fields.get("company"),
            location=fields.get("location"),
            remote=fields.get("remote"),
            posted_date=fields.get("posted_date"),
            salary=fields.get("salary"),
            description=fields.get("description"),
        )
