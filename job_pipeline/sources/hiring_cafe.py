"""HiringCafe source: calls the site's JSON search API directly.

Endpoint and pagination details come from config; the large ``searchState``
filter object is assembled from config defaults plus the per-run keyword,
locations, and date window.
"""

from __future__ import annotations

import copy
import logging
from typing import Any, Dict, Iterator, List, Optional

from ..config import HiringCafeConfig, SearchConfig
from ..http_client import HttpClient
from ..models import JobRecord
from .base import Source, clean_html, guess_remote, to_iso

log = logging.getLogger(__name__)


class HiringCafeSource(Source):
    name = "hiring_cafe"

    def __init__(
        self, cfg: HiringCafeConfig, search: SearchConfig, http: HttpClient
    ) -> None:
        self.cfg = cfg
        self.search = search
        self.http = http

    # ----------------------------------------------------------------- #
    def _build_search_state(self, keyword: str) -> Dict[str, Any]:
        state = copy.deepcopy(self.cfg.search_state_defaults)
        state["searchQuery"] = keyword
        state["dateFetchedPastNDays"] = self.search.date_fetched_past_n_days
        # Represent configured locations as simple formatted-address entries.
        state["locations"] = [
            {"formatted_address": loc, "types": ["custom"]}
            for loc in self.search.locations
        ]
        return state

    def fetch(self) -> Iterator[JobRecord]:
        for keyword in self.search.keywords:
            log.info("[hiring_cafe] searching keyword: %s", keyword)
            yield from self._fetch_keyword(keyword)

    def _fetch_keyword(self, keyword: str) -> Iterator[JobRecord]:
        search_state = self._build_search_state(keyword)
        count = 0
        for page in range(self.search.max_pages_per_run):
            payload = {
                "size": self.cfg.page_size,
                "page": page,
                "searchState": search_state,
            }
            try:
                data = self.http.post_json(
                    self.cfg.search_url, payload, fixture="hiring_cafe"
                )
            except Exception as exc:  # noqa: BLE001 - log and stop this source
                log.error("[hiring_cafe] request failed on page %d: %s", page, exc)
                return

            batch = _extract_batch(data)
            if not batch:
                log.info("[hiring_cafe] no more results at page %d", page)
                break

            for raw in batch:
                rec = self._normalize(raw)
                if rec is not None:
                    count += 1
                    yield rec

            if len(batch) < self.cfg.page_size:
                break

        log.info("[hiring_cafe] keyword '%s' produced %d records", keyword, count)

    # ----------------------------------------------------------------- #
    def _normalize(self, raw: Dict[str, Any]) -> Optional[JobRecord]:
        job = raw.get("job_information", {}) if isinstance(raw, dict) else {}
        data = raw.get("v5_processed_job_data", {}) if isinstance(raw, dict) else {}

        url = (
            raw.get("apply_url")
            or data.get("apply_url")
            or raw.get("url")
            or job.get("url")
        )
        title = job.get("title") or data.get("job_title") or raw.get("title")
        company = (
            data.get("company_name")
            or job.get("company_name")
            or raw.get("company")
        )
        workplace = data.get("workplace_type") or raw.get("workplace_type")
        location = (
            data.get("formatted_workplace_location")
            or raw.get("location")
            or workplace
        )
        salary = _format_salary(data)
        description = clean_html(job.get("description") or raw.get("description"))
        posted = to_iso(
            data.get("estimated_publish_date")
            or raw.get("estimated_publish_date")
            or raw.get("createdAt")
        )
        remote = guess_remote(workplace, location)

        return self.build_record(
            url=url,
            title=title,
            company=company,
            location=location,
            remote=remote,
            posted_date=posted,
            salary=salary,
            description=description,
        )


def _extract_batch(data: Any) -> List[Dict[str, Any]]:
    """Pull the list of raw postings from a variety of response shapes."""
    if isinstance(data, list):
        return data
    if isinstance(data, dict):
        for key in ("results", "jobs", "data", "items", "hits"):
            value = data.get(key)
            if isinstance(value, list):
                return value
            if isinstance(value, dict) and isinstance(value.get("hits"), list):
                return [h.get("_source", h) for h in value["hits"]]
    return []


def _format_salary(data: Dict[str, Any]) -> Optional[str]:
    if not isinstance(data, dict):
        return None
    low = data.get("yearly_min_compensation") or data.get("min_compensation")
    high = data.get("yearly_max_compensation") or data.get("max_compensation")
    currency = data.get("compensation_currency") or "USD"
    if low and high:
        return f"{currency} {low}-{high}"
    if low:
        return f"{currency} {low}+"
    return None
