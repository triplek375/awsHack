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
from .scoring import ResumeScorer, score_and_rank
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

    fetched = len(all_records)

    # 2. Dedupe within this run.
    unique, dropped = dedupe_on_url(all_records)

    # 3. Score every job against the resume and drop those below min_score.
    #    This replaces title keyword filtering: relevance is decided by how
    #    well a posting's skills overlap with the resume, not its title.
    scorer = ResumeScorer(
        skills=cfg.resume.skills,
        weights=cfg.resume.weights,
        default_weight=cfg.resume.default_weight,
    )
    scored, below_threshold = score_and_rank(unique, scorer, cfg.resume.min_score)
    log.info(
        "scored %d jobs; %d matched (>= %.1f), %d dropped below threshold",
        len(unique), len(scored), cfg.resume.min_score, below_threshold,
    )

    # 4. Skip records already persisted in today's partition.
    dt = storage.run_date()
    jsonl_path = storage.partition_path(
        cfg.storage.local_dir, cfg.storage.jsonl_prefix, dt
    )
    existing = storage.load_existing_urls(jsonl_path)
    new_records, skipped_existing = filter_existing(scored, existing)

    # 5. Persist: append new records to the partition JSONL.
    storage.write_jsonl(new_records, jsonl_path, append=True)

    # 6. CSV export reflects the full current partition, ranked by score.
    csv_path = os.path.join(cfg.storage.local_dir, cfg.storage.csv_name)
    all_partition = _read_partition_records(jsonl_path)
    all_partition.sort(key=lambda r: r.match_score or 0.0, reverse=True)
    csv_path = storage.write_csv(all_partition, csv_path)

    # 7. Optional S3 upload of the partition file.
    if cfg.storage.mode == "s3":
        storage.upload_to_s3(jsonl_path, cfg.storage, dt)

    total_skipped = dropped + below_threshold + skipped_existing
    stats = RunStats(
        fetched=fetched, new=len(new_records), skipped=total_skipped
    )
    log.info(
        "run complete: fetched=%d new=%d skipped=%d "
        "(dup_in_run=%d, below_threshold=%d, already_stored=%d)",
        stats.fetched, stats.new, stats.skipped,
        dropped, below_threshold, skipped_existing,
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
            matched = d.get("matched_skills")
            if isinstance(matched, str):
                matched = [s for s in (p.strip() for p in matched.split(",")) if s]
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
                    match_score=d.get("match_score"),
                    matched_skills=matched,
                )
            )
    return records
