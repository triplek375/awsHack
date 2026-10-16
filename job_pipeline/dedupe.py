"""Deduplication on the canonical ``url`` key."""

from __future__ import annotations

from typing import Iterable, List, Set, Tuple

from .models import JobRecord


def dedupe_on_url(records: Iterable[JobRecord]) -> Tuple[List[JobRecord], int]:
    """Collapse records sharing the same url, keeping the first seen.

    Returns (unique_records, num_dropped).
    """
    seen: Set[str] = set()
    unique: List[JobRecord] = []
    dropped = 0
    for rec in records:
        if rec.url in seen:
            dropped += 1
            continue
        seen.add(rec.url)
        unique.append(rec)
    return unique, dropped


def filter_existing(
    records: Iterable[JobRecord], existing_urls: Set[str]
) -> Tuple[List[JobRecord], int]:
    """Drop records whose url already exists in the persisted dataset.

    Returns (new_records, num_skipped).
    """
    new: List[JobRecord] = []
    skipped = 0
    for rec in records:
        if rec.url in existing_urls:
            skipped += 1
            continue
        new.append(rec)
    return new, skipped
