"""Load and validate the YAML configuration into typed dataclasses.

Fails fast with a clear message naming the offending key when something
required is missing or malformed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List

import yaml


class ConfigError(Exception):
    """Raised when the config file is missing or malformed."""


# --------------------------------------------------------------------------- #
# Dataclasses
# --------------------------------------------------------------------------- #
@dataclass
class RetryConfig:
    max_attempts: int = 5
    backoff_base_seconds: float = 1.0
    retry_on_status: List[int] = field(
        default_factory=lambda: [429, 500, 502, 503, 504]
    )


@dataclass
class HttpConfig:
    user_agent: str = "job-data-pipeline/1.0"
    delay_seconds: float = 1.5
    timeout_seconds: float = 30.0
    retry: RetryConfig = field(default_factory=RetryConfig)


@dataclass
class SearchConfig:
    keywords: List[str] = field(default_factory=list)
    locations: List[str] = field(default_factory=list)
    date_fetched_past_n_days: int = 61
    max_pages_per_run: int = 10


@dataclass
class HiringCafeConfig:
    enabled: bool = True
    search_url: str = "https://hiring.cafe/api/search-jobs"
    count_url: str = "https://hiring.cafe/api/search-jobs/get-total-count"
    page_size: int = 100
    search_state_defaults: Dict[str, Any] = field(default_factory=dict)


@dataclass
class AtsConfig:
    enabled: bool = False
    url_template: str = ""
    companies: List[str] = field(default_factory=list)


@dataclass
class SourcesConfig:
    hiring_cafe: HiringCafeConfig = field(default_factory=HiringCafeConfig)
    greenhouse: AtsConfig = field(default_factory=AtsConfig)
    lever: AtsConfig = field(default_factory=AtsConfig)
    ashby: AtsConfig = field(default_factory=AtsConfig)


@dataclass
class S3Config:
    bucket: str = ""
    prefix: str = ""


@dataclass
class StorageConfig:
    mode: str = "local"  # "local" | "s3"
    local_dir: str = "./data"
    jsonl_prefix: str = "jobs"
    csv_name: str = "jobs_latest.csv"
    s3: S3Config = field(default_factory=S3Config)


@dataclass
class Config:
    search: SearchConfig
    http: HttpConfig
    sources: SourcesConfig
    storage: StorageConfig
    offline: bool = False


# --------------------------------------------------------------------------- #
# Loading helpers
# --------------------------------------------------------------------------- #
def _require(mapping: Dict[str, Any], key: str, path: str) -> Any:
    if not isinstance(mapping, dict) or key not in mapping:
        raise ConfigError(f"Missing required config key: '{path}{key}'")
    return mapping[key]


def _ats(raw: Dict[str, Any]) -> AtsConfig:
    raw = raw or {}
    return AtsConfig(
        enabled=bool(raw.get("enabled", False)),
        url_template=str(raw.get("url_template", "")),
        companies=list(raw.get("companies", []) or []),
    )


def load_config(path: str) -> Config:
    """Load, parse, and validate the YAML config at `path`."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            raw = yaml.safe_load(fh)
    except FileNotFoundError as exc:
        raise ConfigError(f"Config file not found: {path}") from exc
    except yaml.YAMLError as exc:
        raise ConfigError(f"Config file is not valid YAML: {exc}") from exc

    if not isinstance(raw, dict):
        raise ConfigError("Config root must be a mapping/object.")

    # search (required)
    search_raw = _require(raw, "search", "")
    keywords = _require(search_raw, "keywords", "search.")
    locations = _require(search_raw, "locations", "search.")
    if not isinstance(keywords, list) or not keywords:
        raise ConfigError("'search.keywords' must be a non-empty list.")
    if not isinstance(locations, list) or not locations:
        raise ConfigError("'search.locations' must be a non-empty list.")
    search = SearchConfig(
        keywords=list(keywords),
        locations=list(locations),
        date_fetched_past_n_days=int(search_raw.get("date_fetched_past_n_days", 61)),
        max_pages_per_run=int(search_raw.get("max_pages_per_run", 10)),
    )

    # http (optional with defaults)
    http_raw = raw.get("http", {}) or {}
    retry_raw = http_raw.get("retry", {}) or {}
    http = HttpConfig(
        user_agent=str(http_raw.get("user_agent", HttpConfig.user_agent)),
        delay_seconds=float(http_raw.get("delay_seconds", 1.5)),
        timeout_seconds=float(http_raw.get("timeout_seconds", 30.0)),
        retry=RetryConfig(
            max_attempts=int(retry_raw.get("max_attempts", 5)),
            backoff_base_seconds=float(retry_raw.get("backoff_base_seconds", 1.0)),
            retry_on_status=list(
                retry_raw.get("retry_on_status", [429, 500, 502, 503, 504])
            ),
        ),
    )

    # sources (required: hiring_cafe)
    sources_raw = _require(raw, "sources", "")
    hc_raw = _require(sources_raw, "hiring_cafe", "sources.")
    hiring_cafe = HiringCafeConfig(
        enabled=bool(hc_raw.get("enabled", True)),
        search_url=str(hc_raw.get("search_url", HiringCafeConfig.search_url)),
        count_url=str(hc_raw.get("count_url", HiringCafeConfig.count_url)),
        page_size=int(hc_raw.get("page_size", 100)),
        search_state_defaults=dict(hc_raw.get("search_state_defaults", {}) or {}),
    )
    sources = SourcesConfig(
        hiring_cafe=hiring_cafe,
        greenhouse=_ats(sources_raw.get("greenhouse", {})),
        lever=_ats(sources_raw.get("lever", {})),
        ashby=_ats(sources_raw.get("ashby", {})),
    )

    # storage (optional with defaults)
    storage_raw = raw.get("storage", {}) or {}
    mode = str(storage_raw.get("mode", "local"))
    if mode not in ("local", "s3"):
        raise ConfigError("'storage.mode' must be 'local' or 's3'.")
    s3_raw = storage_raw.get("s3", {}) or {}
    storage = StorageConfig(
        mode=mode,
        local_dir=str(storage_raw.get("local_dir", "./data")),
        jsonl_prefix=str(storage_raw.get("jsonl_prefix", "jobs")),
        csv_name=str(storage_raw.get("csv_name", "jobs_latest.csv")),
        s3=S3Config(
            bucket=str(s3_raw.get("bucket", "")),
            prefix=str(s3_raw.get("prefix", "")),
        ),
    )

    if mode == "s3" and not storage.s3.bucket:
        raise ConfigError("'storage.s3.bucket' is required when storage.mode is 's3'.")

    return Config(
        search=search,
        http=http,
        sources=sources,
        storage=storage,
        offline=bool(raw.get("offline", False)),
    )
