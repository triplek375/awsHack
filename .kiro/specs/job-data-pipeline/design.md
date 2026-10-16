# Design — Job Data Collection Pipeline

## Overview

The pipeline is a small, modular Python package. A `run()` orchestrator loads YAML
config, invokes each enabled source through a common `fetch()` interface, collects
normalized records, deduplicates on `url`, and writes JSONL + CSV either locally or
to S3. Politeness (delay, User-Agent, retry/backoff) lives in a shared HTTP client
used by every source. An offline mode swaps live HTTP for cached fixtures in
`./samples/`.

Design goals:
- One schema, one `fetch()` interface — adding a source is a single new class.
- No hardcoded values — everything tunable comes from YAML.
- Local-first — works end-to-end with zero cloud/network via the offline demo.

### HiringCafe endpoint (verified)

From inspecting the site's XHR calls (and a public reference implementation), the
site makes JSON `POST` requests to:

- `https://hiring.cafe/api/search-jobs` — body `{ "size": <int>, "page": <int>, "searchState": {...} }`
- `https://hiring.cafe/api/search-jobs/get-total-count` — body `{ "searchState": {...} }`

`searchState` is a large filter object. The fields this pipeline drives from config
are `searchQuery` (keyword), `locations` (array of location objects), and
`dateFetchedPastNDays`. The remaining filter fields are sent as sensible defaults
stored in config so they are not hardcoded in source. Pagination is zero-indexed via
`page`; a page returning fewer than `size` rows (or reaching `max_pages_per_run`)
ends pagination. Because a JSON endpoint exists, Playwright is **not** used.

## Architecture

```
                 ┌──────────────┐
                 │  config.yaml │
                 └──────┬───────┘
                        │ load + validate
                        ▼
      ┌───────────────────────────────────┐
      │            orchestrator            │
      │              run()                 │
      └───┬───────────────┬───────────┬────┘
          │               │           │
   enabled sources   normalize    dedupe(url)
          │               │           │
 ┌────────┴────────┐      │           │
 │  Source.fetch() │──────┘           │
 │  (common iface) │                  ▼
 └───┬────┬────┬───┘           ┌─────────────┐
     │    │    │               │   storage   │
 HiringCafe Greenhouse ...     │ JSONL + CSV │
     │    │    │               │ local / S3  │
     └────┴────┴──── HttpClient └─────────────┘
       (delay, UA, retry/backoff) 
                 │
          offline? → samples/
```

### Module layout

```
job_pipeline/
  __init__.py
  config.py          # load + validate YAML into a typed Config dataclass
  models.py          # JobRecord dataclass + SCHEMA_FIELDS
  http_client.py     # polite HTTP: delay, User-Agent, retry w/ exp backoff; offline fixture loader
  dedupe.py          # dedupe_on_url(records), filter_existing(records, existing_urls)
  storage.py         # write_jsonl, write_csv, local vs S3 dispatch
  sources/
    __init__.py
    base.py          # Source ABC: fetch() -> Iterator[JobRecord]; shared normalize helpers
    hiring_cafe.py   # HiringCafeSource
    greenhouse.py    # GreenhouseSource
    lever.py         # LeverSource
    ashby.py         # AshbySource
  cli.py             # arg parsing (--config, --offline, --local/--s3), calls run()
  pipeline.py        # run(config): orchestration + logging of fetched/new/skipped
config.yaml
samples/
  hiring_cafe.json
  greenhouse.json
  lever.json
  ashby.json
tests/
  test_normalization.py
  test_dedupe.py
  conftest.py        # loads fixtures from samples/
data/                # local output (gitignored)
README.md
requirements.txt
```

## Components and Interfaces

### Config (`config.py`)

Loads YAML into a validated `Config` dataclass. Fails fast with a clear message
naming any missing/malformed key. Shape:

```yaml
search:
  keywords: ["data engineer", "cloud engineer"]   # each becomes a HiringCafe query
  locations: ["Texas", "remote US"]
  date_fetched_past_n_days: 61
  max_pages_per_run: 10

http:
  user_agent: "job-data-pipeline/1.0 (+contact@example.com)"
  delay_seconds: 1.5          # delay between requests
  retry:
    max_attempts: 5
    backoff_base_seconds: 1.0 # exp backoff: base * 2**attempt
    retry_on_status: [429, 500, 502, 503, 504]
  timeout_seconds: 30

sources:
  hiring_cafe:
    enabled: true
    search_url: "https://hiring.cafe/api/search-jobs"
    count_url: "https://hiring.cafe/api/search-jobs/get-total-count"
    page_size: 100
    # default searchState filters live here so they are config, not code
    search_state_defaults: { ... }
  greenhouse:
    enabled: false
    url_template: "https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true"
    companies: []
  lever:
    enabled: false
    url_template: "https://api.lever.co/v0/postings/{company}?mode=json"
    companies: []
  ashby:
    enabled: false
    url_template: "https://api.ashbyhq.com/posting-api/job-board/{company}"
    companies: []

storage:
  mode: "local"               # "local" | "s3"
  local_dir: "./data"
  jsonl_prefix: "jobs"        # -> jobs/dt=YYYY-MM-DD/run.jsonl
  csv_name: "jobs_latest.csv"
  s3:
    bucket: ""
    prefix: ""

offline: false               # when true, read from samples/ instead of network
```

### JobRecord (`models.py`)

```python
SCHEMA_FIELDS = ["url", "title", "company", "location", "remote",
                 "posted_date", "salary", "description", "source", "fetched_at"]

@dataclass
class JobRecord:
    url: str                      # unique key, required
    title: str | None
    company: str | None
    location: str | None
    remote: bool | None
    posted_date: str | None       # ISO-8601 or None
    salary: str | None
    description: str | None
    source: str                   # "hiring_cafe" | "greenhouse" | ...
    fetched_at: str               # ISO-8601 UTC
```

Missing optional values are `None` (serialized as JSON `null`). A record with no
`url` is never constructed; the source skips and logs it.

### HttpClient (`http_client.py`)

A thin wrapper over `requests.Session` that enforces politeness in one place:

```python
class HttpClient:
    def __init__(self, cfg: HttpConfig, offline: bool = False): ...
    def get_json(self, url, **kw) -> Any: ...
    def post_json(self, url, json, **kw) -> Any: ...
```

- Sets the configured `User-Agent`.
- Sleeps `delay_seconds` before each live request.
- Retries on configured transient statuses/exceptions with exponential backoff
  (`backoff_base_seconds * 2**attempt`, attempt 0-indexed), capped at `max_attempts`.
- When `offline=True`, `get_json`/`post_json` return parsed fixtures from `samples/`
  (resolved by source name) instead of hitting the network — same code path for the
  rest of the pipeline.

### Source interface (`sources/base.py`)

```python
class Source(ABC):
    name: str
    @abstractmethod
    def fetch(self) -> Iterator[JobRecord]:
        """Yield normalized JobRecords for this source."""
```

Each source owns: how to page the upstream API, and how to map a raw posting to a
`JobRecord`. Shared helpers in `base.py`: `now_utc_iso()`, `to_iso(date)`,
`guess_remote(text/fields)`, `clean_html(desc)`, `build_record(**fields)` (enforces
URL presence, fills `fetched_at`).

Per-source normalization notes:

- **HiringCafe**: POST paginated search. Map job object → url (apply/job URL),
  title, company, location, remote (from workplace type), posted_date, salary
  (from compensation fields if present), description (HTML-cleaned).
- **Greenhouse**: GET per company; `jobs[]` → `absolute_url`, `title`,
  company=slug, `location.name`, `content` (HTML) as description, `updated_at` as
  posted_date; salary usually absent → `null`.
- **Lever**: GET per company; list of postings → `hostedUrl`, `text` (title),
  company=slug, `categories.location`, `categories.commitment`,
  `createdAt` → posted_date, `description`/`descriptionPlain`.
- **Ashby**: GET per company; `jobs[]` → `jobUrl`/`applyUrl`, `title`, company=slug,
  `location`, `isRemote`, `publishedAt`, `compensation` if present, `descriptionHtml`.

### Dedupe (`dedupe.py`)

```python
def dedupe_on_url(records: Iterable[JobRecord]) -> tuple[list[JobRecord], int]:
    """Collapse same-url records, keep first. Returns (unique, num_dropped)."""

def filter_existing(records, existing_urls: set[str]) -> tuple[list[JobRecord], int]:
    """Drop records whose url is already persisted. Returns (new, num_skipped)."""
```

The orchestrator loads existing URLs from the current date partition's `run.jsonl`
(if present) so re-running the same day never duplicates.

### Storage (`storage.py`)

- `write_jsonl(records, path)` — one JSON object per line.
- `write_csv(records, path)` — flat CSV of SCHEMA_FIELDS for quick viewing.
- `partition_path(base, prefix, date)` → `{base}/{prefix}/dt=YYYY-MM-DD/run.jsonl`.
- Local mode writes under `storage.local_dir`. S3 mode writes the local copy first,
  then uploads via `boto3` to `s3://{bucket}/{prefix}/...`; on upload failure it logs
  and keeps the local copy (no data loss).

### Orchestrator (`pipeline.py`)

```python
def run(config: Config) -> RunStats:
    1. build HttpClient(config.http, offline=config.offline)
    2. for each enabled source: records += list(source.fetch())  # per-source counts logged
    3. unique, dropped = dedupe_on_url(records)
    4. existing = load_existing_urls(partition)                  # same-day re-run safety
       new, skipped = filter_existing(unique, existing)
    5. write JSONL (append new to partition) + CSV export
    6. if storage.mode == "s3": upload partition file
    7. log fetched=len(records), new=len(new), skipped=dropped+skipped
```

`RunStats{fetched, new, skipped}` is returned for tests and logging.

## Data flow (offline demo)

`cli --offline` → `run()` → each source's `fetch()` calls `HttpClient` which returns
the matching `samples/*.json` fixture → normalize → dedupe → write `./data/...jsonl`
and `./data/jobs_latest.csv`. No network, no AWS. This is the demo path and is
exactly what the unit tests exercise for normalization.

## Error Handling

- Per-slug / per-page failures are caught, logged, and skipped; the run continues.
- Non-200 or non-JSON HiringCafe responses stop that source's pagination only.
- Missing optional fields → `null`; missing `url` → record skipped + logged.
- Malformed/missing required config → fail fast with the offending key named.
- S3 upload failure → logged, local copy retained.

## Testing Strategy

- `test_normalization.py`: feed each source its `samples/*.json` fixture through
  `fetch()` (offline client) and assert the resulting `JobRecord` fields, including
  that missing optional fields become `null` and records still produce.
- `test_dedupe.py`: assert `dedupe_on_url` collapses duplicate URLs and
  `filter_existing` skips already-persisted URLs; assert reported counts.
- All tests are offline (fixtures only), run with `pytest`.

## Dependencies

- `requests`, `PyYAML` (core)
- `boto3` (S3 upload; only needed for S3 mode)
- `pytest` (dev/test)
- No Playwright (JSON endpoint exists).

## Phasing (maps to build order)

1. **Phase 1**: config, models, http_client (+offline), HiringCafe source, dedupe,
   local JSONL+CSV storage, logging, samples, tests, README. Fully working locally.
2. **Phase 2**: S3 upload in storage + `storage.mode: s3`.
3. **Phase 3 (optional)**: `lambda_handler` entrypoint + EventBridge schedule notes
   / IaC. Does not block Phases 1–2.

ATS sources (Greenhouse/Lever/Ashby) are built in Phase 1's source framework but
ship disabled by default (empty slug lists), satisfying "optional second source."
