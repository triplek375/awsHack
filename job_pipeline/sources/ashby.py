"""Ashby ATS source (optional).

Endpoint: https://api.ashbyhq.com/posting-api/job-board/{company}
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterator, Optional

from ..config import AtsConfig
from ..http_client import HttpClient
from ..models import JobRecord
from .base import Source, clean_html, guess_remote, to_iso

log = logging.getLogger(__name__)


class AshbySource(Source):
    name = "ashby"

    def __init__(self, cfg: AtsConfig, http: HttpClient) -> None:
        self.cfg = cfg
        self.http = http

    def fetch(self) -> Iterator[JobRecord]:
        for company in self.cfg.companies:
            url = self.cfg.url_template.format(company=company)
            try:
                data = self.http.get_json(url, fixture="ashby")
            except Exception as exc:  # noqa: BLE001 - continue with other slugs
                log.error("[ashby] failed for '%s': %s", company, exc)
                continue
            jobs = data.get("jobs", []) if isinstance(data, dict) else []
            for raw in jobs:
                rec = self._normalize(raw, company)
                if rec is not None:
                    yield rec

    def _normalize(self, raw: Dict[str, Any], company: str) -> Optional[JobRecord]:
        remote_flag = raw.get("isRemote")
        location = raw.get("location")
        return self.build_record(
            url=raw.get("jobUrl") or raw.get("applyUrl"),
            title=raw.get("title"),
            company=company,
            location=location,
            remote=remote_flag if isinstance(remote_flag, bool)
            else guess_remote(location),
            posted_date=to_iso(raw.get("publishedAt") or raw.get("updatedAt")),
            salary=_compensation(raw),
            description=clean_html(raw.get("descriptionHtml") or raw.get("descriptionPlain")),
        )


def _compensation(raw: Dict[str, Any]) -> Optional[str]:
    comp = raw.get("compensation") or {}
    summary = comp.get("compensationTierSummary") if isinstance(comp, dict) else None
    return summary or None
