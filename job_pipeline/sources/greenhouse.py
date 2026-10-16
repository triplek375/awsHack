"""Greenhouse ATS source (optional).

Endpoint: https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterator, Optional

from ..config import AtsConfig
from ..http_client import HttpClient
from ..models import JobRecord
from .base import Source, clean_html, guess_remote, to_iso

log = logging.getLogger(__name__)


class GreenhouseSource(Source):
    name = "greenhouse"

    def __init__(self, cfg: AtsConfig, http: HttpClient) -> None:
        self.cfg = cfg
        self.http = http

    def fetch(self) -> Iterator[JobRecord]:
        for company in self.cfg.companies:
            url = self.cfg.url_template.format(company=company)
            try:
                data = self.http.get_json(url, fixture="greenhouse")
            except Exception as exc:  # noqa: BLE001 - continue with other slugs
                log.error("[greenhouse] failed for '%s': %s", company, exc)
                continue
            for raw in data.get("jobs", []) if isinstance(data, dict) else []:
                rec = self._normalize(raw, company)
                if rec is not None:
                    yield rec

    def _normalize(self, raw: Dict[str, Any], company: str) -> Optional[JobRecord]:
        location = (raw.get("location") or {}).get("name")
        return self.build_record(
            url=raw.get("absolute_url"),
            title=raw.get("title"),
            company=company,
            location=location,
            remote=guess_remote(location),
            posted_date=to_iso(raw.get("updated_at") or raw.get("first_published")),
            salary=None,
            description=clean_html(raw.get("content")),
        )
