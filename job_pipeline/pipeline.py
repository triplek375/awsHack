"""Orchestrator: fetch -> dedupe -> filter-existing -> store, with logging."""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from typing import List

from .config import Config
from .dedupe import dedupe_on_url, filter_existing
from .http_client import HttpClient
from .models import JobRecord
from .sources.ashby import AshbySource
from .sources.base import Source
from .sources.greenhouse import GreenhouseSource
from .sources.hiring_cafe import HiringCafeSource
from .sources.lever import LeverSource
from . import storage

log = logging.getLogger(__name__)


@dataclass
class RunStats:
    fetched: int
    new: int
    skipped: int


_ATS_SOURCES = {"greenhouse", "lever", "ashby"}


def _filter_ats_by_keywords(
    records: List[JobRecord], keywords: List[str]
) -> List[JobRecord]:
    """Keep ATS records whose title contains any keyword token.

    Non-ATS records (e.g. HiringCafe) pass through unchanged. A record with no
    title is dropped only for ATS sources, since the role cannot be confirmed.
    """
    if not keywords:
        return records
    terms = [k.lower() for k in keywords]
    kept: List[JobRecord] = []
    for rec in records:
        if rec.source not in _ATS_SOURCES:
            kept.append(rec)
            continue
        title = (rec.title or "").lower()
        if any(term in title for term in terms):
            kept.append(rec)
    return kept


def _build_sources(cfg: Config, http: HttpClient) -> List[Source]:
    sources: List[Source] = []
    if cfg.sources.hiring_cafe.enabled:
        sources.append(HiringCafeSource(cfg.sources.hiring_cafe, cfg.search, http))
    if cfg.sources.greenhouse.enabled and cfg.sources.greenhouse.companies:
        sources.append(GreenhouseSource(cfg.sources.greenhouse, http))
    if cfg.sources.lever.enabled and cfg.sources.lever.companies:
        sources.append(LeverSource(cfg.sources.lever, http))
    if cfg.sources.ashby.enabled and cfg.sources.ashby.companies:
        sources.append(AshbySource(cfg.sources.ashby, http))
    return sources


def run(cfg: Config) -> RunStats:
    http = HttpClient(cfg.http, offline=cfg.offline)
    sources = _build_sources(cfg, http)
    if not sources:
        log.warning("no sources enabled; nothing to do")
        return RunStats(0, 0, 0)

    # 1. Fetch from each enabled source.
    all_records: List[JobRecord] = []
    for source in sources:
        before = len(all_records)
        for rec in source.fetch():
            all_records.append(rec)
        log.info("[%s] fetched %d records", source.name, len(all_records) - before)

    # 1a. ATS boards return every posting on a company board; narrow to the
    #     searched role(s) by matching keywords against the job title.
    #     HiringCafe filters server-side, so its records are left untouched.
    all_records = _filter_ats_by_keywords(all_records, cfg.search.keywords)

    fetched = len(all_records)

    # 2. Dedupe within this run.
    unique, dropped = dedupe_on_url(all_records)

    # 3. Skip records already persisted in today's partition.
    dt = storage.run_date()
    jsonl_path = storage.partition_path(
        cfg.storage.local_dir, cfg.storage.jsonl_prefix, dt
    )
    existing = storage.load_existing_urls(jsonl_path)
    new_records, skipped_existing = filter_existing(unique, existing)

    # 4. Persist: append new records to the partition JSONL.
    storage.write_jsonl(new_records, jsonl_path, append=True)

    # 5. CSV export reflects the full current partition (existing + new).
    csv_path = os.path.join(cfg.storage.local_dir, cfg.storage.csv_name)
    all_partition = _read_partition_records(jsonl_path)
    storage.write_csv(all_partition, csv_path)

    # 6. Optional S3 upload of the partition file.
    if cfg.storage.mode == "s3":
        storage.upload_to_s3(jsonl_path, cfg.storage, dt)

    total_skipped = dropped + skipped_existing
    stats = RunStats(
        fetched=fetched, new=len(new_records), skipped=total_skipped
    )
    log.info(
        "run complete: fetched=%d new=%d skipped=%d (dup_in_run=%d, already_stored=%d)",
        stats.fetched, stats.new, stats.skipped, dropped, skipped_existing,
    )
    log.info("JSONL: %s", jsonl_path)
    log.info("CSV:   %s", csv_path)
    return stats


def _read_partition_records(jsonl_path: str) -> List[JobRecord]:
    """Reload the partition JSONL into JobRecords for the CSV export."""
    import json

    records: List[JobRecord] = []
    if not os.path.exists(jsonl_path):
        return records
    with open(jsonl_path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                continue
            records.append(
                JobRecord(
                    url=d.get("url"),
                    source=d.get("source"),
                    fetched_at=d.get("fetched_at"),
                    title=d.get("title"),
                    company=d.get("company"),
                    location=d.get("location"),
                    remote=d.get("remote"),
                    posted_date=d.get("posted_date"),
                    salary=d.get("salary"),
                    description=d.get("description"),
                )
            )
    return records
