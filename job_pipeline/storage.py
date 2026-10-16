"""Persistence: date-partitioned JSONL plus a flat CSV export.

Local mode writes under the configured local dir. S3 mode (Phase 2) writes the
local copy first, then uploads; on upload failure the local copy is retained.
"""

from __future__ import annotations

import csv
import json
import logging
import os
from datetime import date
from typing import Iterable, List, Set

from .config import StorageConfig
from .models import SCHEMA_FIELDS, JobRecord

log = logging.getLogger(__name__)


def run_date() -> str:
    """Partition date string YYYY-MM-DD (local date)."""
    return date.today().isoformat()


def partition_path(local_dir: str, prefix: str, dt: str) -> str:
    """Return {local_dir}/{prefix}/dt=YYYY-MM-DD/run.jsonl."""
    return os.path.join(local_dir, prefix, f"dt={dt}", "run.jsonl")


def load_existing_urls(path: str) -> Set[str]:
    """Read urls already present in a partition's JSONL (for re-run safety)."""
    urls: Set[str] = set()
    if not os.path.exists(path):
        return urls
    with open(path, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                urls.add(json.loads(line)["url"])
            except (json.JSONDecodeError, KeyError):
                continue
    return urls


def write_jsonl(records: Iterable[JobRecord], path: str, append: bool = True) -> int:
    """Write records as JSON Lines. Returns number of lines written."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    mode = "a" if append and os.path.exists(path) else "w"
    written = 0
    with open(path, mode, encoding="utf-8") as fh:
        for rec in records:
            fh.write(json.dumps(rec.to_dict(), ensure_ascii=False) + "\n")
            written += 1
    return written


def write_csv(records: List[JobRecord], path: str) -> int:
    """Write a flat CSV of all records (overwrites). Returns row count."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=SCHEMA_FIELDS)
        writer.writeheader()
        for rec in records:
            writer.writerow(rec.to_dict())
    return len(records)


def upload_to_s3(local_path: str, cfg: StorageConfig, dt: str) -> None:
    """Upload the partition JSONL to S3. Local copy is kept on failure."""
    key = f"{cfg.s3.prefix.rstrip('/')}/{cfg.jsonl_prefix}/dt={dt}/run.jsonl"
    key = key.lstrip("/")
    try:
        import boto3  # imported lazily so local mode needs no boto3

        client = boto3.client("s3")
        client.upload_file(local_path, cfg.s3.bucket, key)
        log.info("uploaded to s3://%s/%s", cfg.s3.bucket, key)
    except Exception as exc:  # noqa: BLE001 - retain local copy, do not crash
        log.error(
            "S3 upload failed (local copy retained at %s): %s", local_path, exc
        )
