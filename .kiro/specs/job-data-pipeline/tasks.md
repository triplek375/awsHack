# Implementation Plan — Job Data Collection Pipeline

## Phase 1 — Local pipeline (fetch + normalize + dedupe, CSV/JSONL)

- [-] 1. Project scaffolding and dependencies
  - Create `job_pipeline/` package, `requirements.txt` (requests, PyYAML, boto3, pytest),
    and `.gitignore` entry for `./data/`.
  - _Requirements: 7, 12.1_

- [ ] 2. Config loading and validation
  - [~] 2.1 Define `Config` dataclasses and `load_config(path)` in `config.py`.
    - Parse the YAML shape from the design; fail fast with the offending key named.
    - _Requirements: 7.1, 7.2, 7.3, 7.4_
  - [~] 2.2 Author `config.yaml` with search keywords/locations, source flags/endpoints,
        pagination, delay, retry, User-Agent, storage mode, and HiringCafe searchState
        defaults.
    - _Requirements: 1.2, 2.1, 6.1, 6.2, 6.3, 7.2, 7.4_

- [~] 3. Data model
  - Implement `JobRecord` dataclass and `SCHEMA_FIELDS` in `models.py`; optional fields
    default to `None`; `fetched_at` is ISO-8601 UTC.
  - _Requirements: 3.2, 3.3, 3.5_

- [~] 4. Polite HTTP client with offline support
  - Implement `HttpClient` in `http_client.py`: configurable User-Agent, inter-request
    delay, retry with exponential backoff on configured transient statuses/exceptions,
    and an offline mode that returns `samples/*.json` fixtures.
  - _Requirements: 6.1, 6.2, 6.3, 8.3, 9.1_

- [~] 5. Source framework and normalization helpers
  - Implement `Source` ABC with `fetch()` and shared helpers (`now_utc_iso`, `to_iso`,
    `guess_remote`, `clean_html`, `build_record` enforcing URL presence) in
    `sources/base.py`.
  - _Requirements: 3.1, 3.2, 3.4, 3.6_

- [~] 6. HiringCafe source
  - Implement `HiringCafeSource.fetch()`: POST paginated search using config-driven
    searchState (query, locations, date window), stop at `max_pages_per_run` or short
    page; normalize each posting to `JobRecord`; handle non-200/non-JSON by logging and
    stopping pagination.
  - _Requirements: 1.1, 1.2, 1.3, 1.4, 1.5, 3.2, 3.3, 8.2_

- [ ] 7. Optional ATS sources (shipped disabled by default)
  - [~] 7.1 Implement `GreenhouseSource` (jobs + `content=true`, per-slug loop, continue on failure).
    - _Requirements: 2.1, 2.2, 2.3, 3.2, 3.3_
  - [~] 7.2 Implement `LeverSource` (`mode=json`, per-slug loop, continue on failure).
    - _Requirements: 2.1, 2.2, 2.3, 3.2, 3.3_
  - [~] 7.3 Implement `AshbySource` (job-board posting API, per-slug loop, continue on failure).
    - _Requirements: 2.1, 2.2, 2.3, 3.2, 3.3_

- [~] 8. Deduplication
  - Implement `dedupe_on_url` and `filter_existing` in `dedupe.py`, returning dropped/
    skipped counts.
  - _Requirements: 4.1, 4.2, 4.3_

- [~] 9. Local storage (JSONL + CSV)
  - Implement `storage.py`: `partition_path` (`jobs/dt=YYYY-MM-DD/run.jsonl`),
    `write_jsonl`, `write_csv`, and `load_existing_urls` for same-day re-run safety.
  - _Requirements: 5.1, 5.3, 5.4, 4.2_

- [~] 10. Orchestrator, CLI, and logging
  - Implement `run(config)` in `pipeline.py` wiring fetch → dedupe → filter-existing →
    write JSONL+CSV, returning `RunStats`; log fetched/new/skipped and per-source counts.
    Implement `cli.py` with `--config`, `--offline`, `--local/--s3`.
  - _Requirements: 3.1, 4.3, 5.3, 8.1, 8.2, 9.2, 12.1_

- [~] 11. Cached sample fixtures for offline demo
  - Add representative `samples/hiring_cafe.json` (and greenhouse/lever/ashby) captured/
    trimmed from real responses so `--offline` runs end-to-end with no network.
  - _Requirements: 9.1, 9.2, 9.3_

- [~] 12. Unit tests (normalization + dedupe)
  - `test_normalization.py` per source from fixtures incl. missing-optional → `null`;
    `test_dedupe.py` for same-url collapse and skip-existing. All offline.
  - _Requirements: 10.1, 10.2, 10.3_

- [~] 13. README
  - Short run instructions: install, config, run local, run offline demo, enable S3.
  - _Requirements: 11.1_

## Phase 2 — S3 upload

- [~] 14. S3 storage mode
  - Extend `storage.py` to upload the partition JSONL via `boto3` when
    `storage.mode == "s3"`; write local copy first and retain it if upload fails; wire
    the `--s3` flag.
  - _Requirements: 5.2, 5.3, 5.5_

## Phase 3 — Optional scheduling (does not block Phases 1–2)

- [ ] 15. AWS Lambda + EventBridge
  - [~] 15.1 Add a `lambda_handler` entrypoint that calls `run()` with S3 mode and bundle
        guidance (packaging/deps).
    - _Requirements: 12.3_
  - [~] 15.2 Document/define an EventBridge schedule to invoke the Lambda on a cadence.
    - _Requirements: 12.3_
