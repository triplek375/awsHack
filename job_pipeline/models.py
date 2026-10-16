"""Normalized job record schema shared by every source."""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import List, Optional

# The canonical output schema. Order matters for CSV column ordering.
# match_score / matched_skills are populated by the scoring step; they sort
# first so the most relevant columns lead in the CSV.
SCHEMA_FIELDS = [
    "match_score",
    "matched_skills",
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

    `match_score` (0-100) and `matched_skills` are filled by the scoring step;
    they stay at their defaults until a job is scored against the resume.
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
    match_score: Optional[float] = None
    matched_skills: Optional[List[str]] = None

    def to_dict(self) -> dict:
        """Return a dict ordered by SCHEMA_FIELDS.

        `matched_skills` is rendered as a comma-separated string so it reads
        cleanly in the CSV; JSONL consumers can split on ', '.
        """
        raw = asdict(self)
        out = {}
        for field in SCHEMA_FIELDS:
            value = raw.get(field)
            if field == "matched_skills" and isinstance(value, list):
                value = ", ".join(value)
            out[field] = value
        return out
