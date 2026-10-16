"""Normalized job record schema shared by every source."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Optional

# The canonical output schema. Order matters for CSV column ordering.
SCHEMA_FIELDS = [
    "url",
    "title",
    "company",
    "location",
    "remote",
    "posted_date",
    "salary",
    "description",
    "source",
    "fetched_at",
]


@dataclass
class JobRecord:
    """One normalized job posting.

    `url` is the unique dedupe key and is required. `source` and `fetched_at`
    are always set by the pipeline. Every other field is optional and becomes
    JSON ``null`` when a source does not provide it.
    """

    url: str
    source: str
    fetched_at: str
    title: Optional[str] = None
    company: Optional[str] = None
    location: Optional[str] = None
    remote: Optional[bool] = None
    posted_date: Optional[str] = None
    salary: Optional[str] = None
    description: Optional[str] = None

    def to_dict(self) -> dict:
        """Return a dict ordered by SCHEMA_FIELDS."""
        raw = asdict(self)
        return {field: raw.get(field) for field in SCHEMA_FIELDS}
