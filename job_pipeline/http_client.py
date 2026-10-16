"""Polite HTTP client: User-Agent, inter-request delay, retry with
exponential backoff, and an offline mode that serves cached fixtures.
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import Any, Optional

import requests

from .config import HttpConfig

log = logging.getLogger(__name__)

SAMPLES_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "samples"
)


class HttpClient:
    """Thin wrapper over requests.Session enforcing politeness in one place.

    When ``offline`` is True, ``get_json``/``post_json`` return parsed JSON from
    ``samples/<fixture>.json`` instead of hitting the network. The caller passes
    ``fixture`` to identify which cached response to load.
    """

    def __init__(self, cfg: HttpConfig, offline: bool = False) -> None:
        self.cfg = cfg
        self.offline = offline
        self._session = requests.Session()
        self._session.headers.update(
            {
                "User-Agent": cfg.user_agent,
                "Accept": "application/json, text/plain, */*",
                "Content-Type": "application/json",
            }
        )

    # ----------------------------------------------------------------- #
    # Public API
    # ----------------------------------------------------------------- #
    def get_json(self, url: str, fixture: Optional[str] = None, **kwargs: Any) -> Any:
        if self.offline:
            return self._load_fixture(fixture)
        return self._request("GET", url, **kwargs)

    def post_json(
        self,
        url: str,
        json_body: Any,
        fixture: Optional[str] = None,
        **kwargs: Any,
    ) -> Any:
        if self.offline:
            return self._load_fixture(fixture)
        return self._request("POST", url, json=json_body, **kwargs)

    # ----------------------------------------------------------------- #
    # Internals
    # ----------------------------------------------------------------- #
    def _load_fixture(self, fixture: Optional[str]) -> Any:
        if not fixture:
            raise ValueError("offline mode requires a fixture name")
        path = os.path.join(SAMPLES_DIR, f"{fixture}.json")
        log.debug("offline: loading fixture %s", path)
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def _request(self, method: str, url: str, **kwargs: Any) -> Any:
        retry = self.cfg.retry
        last_exc: Optional[Exception] = None

        for attempt in range(retry.max_attempts):
            # Polite delay before every live request.
            time.sleep(self.cfg.delay_seconds)
            try:
                resp = self._session.request(
                    method, url, timeout=self.cfg.timeout_seconds, **kwargs
                )
            except requests.RequestException as exc:
                last_exc = exc
                wait = retry.backoff_base_seconds * (2 ** attempt)
                log.warning(
                    "request error (%s) on %s, attempt %d/%d, backing off %.1fs: %s",
                    method, url, attempt + 1, retry.max_attempts, wait, exc,
                )
                time.sleep(wait)
                continue

            if resp.status_code in retry.retry_on_status:
                wait = retry.backoff_base_seconds * (2 ** attempt)
                log.warning(
                    "transient status %d on %s, attempt %d/%d, backing off %.1fs",
                    resp.status_code, url, attempt + 1, retry.max_attempts, wait,
                )
                time.sleep(wait)
                continue

            resp.raise_for_status()
            return resp.json()

        raise RuntimeError(
            f"request to {url} failed after {retry.max_attempts} attempts"
        ) from last_exc
