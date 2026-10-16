"""Lever ATS source (optional).

Endpoint: https://api.lever.co/v0/postings/{company}?mode=json
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Iterator, Optional

from ..config import AtsConfig
from ..http_client import HttpClient
from ..models import JobRecord
from .base import Source, clean_html, guess_remote, to_iso

log = logging.getLogger(__name__)


class LeverSource(Source):
    name = "lever"

    def __init__(self, cfg: AtsConfig, http: HttpClient) -> None:
        self.cfg = cfg
        self.http = http

    def fetch(self) -> Iterator[JobRecord]:
        for company in self.cfg.companies:
            url = self.cfg.url_template.format(company=company)
            try:
                data = self.http.get_json(url, fixture="lever")
            except Exception as exc:  # noqa: BLE001 - continue with other slugs
                log.error("[lever] failed for '%s': %s", company, exc)
                continue
            for raw in data if isinstance(data, list) else []:
                rec = self._normalize(raw, company)
                if rec is not None:
                    yield rec

    def _normalize(self, raw: Dict[str, Any], company: str) -> Optional[JobRecord]:
        categories = raw.get("categories", {}) or {}
        location = categories.get("location")
        workplace = categories.get("workplaceType")
        description = raw.get("descriptionPlain") or clean_html(raw.get("description"))
        return self.build_record(
            url=raw.get("hostedUrl") or raw.get("applyUrl"),
            title=raw.get("text"),
            company=company,
            location=location,
            remote=guess_remote(workplace, location),
            posted_date=to_iso(raw.get("createdAt")),
            salary=(raw.get("salaryRange") or {}).get("currency") and _salary(raw),
            description=description,
        )


def _salary(raw: Dict[str, Any]) -> Optional[str]:
    sr = raw.get("salaryRange") or {}
    if sr.get("min") and sr.get("max"):
        return f"{sr.get('currency', '')} {sr['min']}-{sr['max']}".strip()
    return None
