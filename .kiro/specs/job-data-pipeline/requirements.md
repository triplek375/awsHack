# Requirements — Job Data Collection Pipeline

## Introduction

A Python pipeline that fetches job postings from one or more sources, normalizes
them into a single clean schema, deduplicates on job URL, and persists the result
as JSON Lines (one file per run, partitioned by date) plus a local CSV export for
quick viewing. The pipeline runs locally by default and can optionally upload to
Amazon S3. There is no scoring, no notifications, and no UI — the sole goal is
clean, structured job data.

Primary source is HiringCafe, called through its public JSON API
(`POST https://hiring.cafe/api/search-jobs`). An optional set of public ATS APIs
(Greenhouse, Lever, Ashby) can be enabled per a configurable list of company slugs.

All tunable values (endpoints, keywords, locations, pagination, storage mode) live
in a YAML config file. No values are hardcoded in source.

## Glossary

- **Source**: A provider of job postings (HiringCafe, Greenhouse, Lever, Ashby).
- **Record**: One normalized job posting conforming to the output schema.
- **Run**: A single end-to-end execution of the pipeline.
- **Dedupe key**: The canonical `url` field; identical URLs are the same job.
- **Local mode**: Output written to `./data/` instead of S3.

## Requirements

### Requirement 1 — Fetch from HiringCafe via JSON API

**User Story:** As a data collector, I want to pull job postings from HiringCafe's
JSON endpoint, so that I get structured data without scraping rendered HTML.

#### Acceptance Criteria

1. WHEN the pipeline runs with HiringCafe enabled THEN the system SHALL send an
   HTTP POST to the configured HiringCafe search endpoint with a JSON body
   containing `size`, `page`, and `searchState`.
2. WHEN building `searchState` THEN the system SHALL populate the search query,
   locations, and date-window fields from the YAML config rather than hardcoded
   values.
3. WHEN more results exist than one page returns THEN the system SHALL paginate by
   incrementing the `page` field until either no more results are returned or the
   configured `max_pages_per_run` limit is reached.
4. IF the HiringCafe response status is not 200 OR the body is not valid JSON THEN
   the system SHALL log the failure and stop paginating that source without
   crashing the run.
5. IF no JSON endpoint were available THEN the design SHALL fall back to a headless
   browser (Playwright); because a JSON endpoint exists, Playwright SHALL NOT be a
   runtime dependency.

### Requirement 2 — Optional ATS sources (Greenhouse, Lever, Ashby)

**User Story:** As a data collector, I want to optionally pull postings directly
from company ATS boards, so that I can target specific employers.

#### Acceptance Criteria

1. WHEN an ATS source is enabled in config with a list of company slugs THEN the
   system SHALL fetch jobs for each slug from that provider's public endpoint:
   - Greenhouse: `https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true`
   - Lever: `https://api.lever.co/v0/postings/{company}?mode=json`
   - Ashby: `https://api.ashbyhq.com/posting-api/job-board/{company}`
2. WHEN an ATS source is disabled OR its slug list is empty THEN the system SHALL
   skip that source entirely.
3. IF a single company slug fails (network error, 404, bad JSON) THEN the system
   SHALL log the error and continue with the remaining slugs rather than aborting
   the run.

### Requirement 3 — Common fetch interface and normalization

**User Story:** As a maintainer, I want every source to expose the same interface
and output the same schema, so that adding sources is low-friction and downstream
data is uniform.

#### Acceptance Criteria

1. WHEN any source is invoked THEN it SHALL be reached through a common `fetch()`
   interface that yields normalized records.
2. WHEN a raw posting is normalized THEN the resulting record SHALL contain exactly
   these fields: `url` (unique key), `title`, `company`, `location`, `remote`
   (bool), `posted_date`, `salary`, `description`, `source`, `fetched_at`.
3. WHEN a source does not provide a value for an optional field (e.g. `salary`,
   `posted_date`) THEN the system SHALL set that field to `null` rather than
   omitting it or failing.
4. WHEN `remote` cannot be determined from an explicit flag THEN the system SHALL
   derive a best-effort boolean from available location/workplace fields.
5. WHEN `posted_date` and `fetched_at` are written THEN they SHALL be ISO-8601
   strings (`fetched_at` in UTC).
6. WHEN a posting has no resolvable `url` THEN the system SHALL skip the record and
   log it, because `url` is the required dedupe key.

### Requirement 4 — Deduplication

**User Story:** As a data collector, I want duplicate jobs removed on URL, so that
re-running the pipeline never creates duplicates.

#### Acceptance Criteria

1. WHEN two or more records share the same `url` within a run THEN the system SHALL
   keep exactly one and discard the rest.
2. WHEN a record's `url` already exists in the persisted dataset for the current
   run's partition THEN the system SHALL treat it as a duplicate and not write it
   again.
3. WHEN deduplication completes THEN the system SHALL log counts of total fetched,
   new, and skipped-as-duplicate.

### Requirement 5 — Storage (JSONL + CSV, local or S3)

**User Story:** As a data collector, I want output saved as date-partitioned JSONL
with a CSV for quick viewing, locally or in S3, so that the data is easy to store
and inspect.

#### Acceptance Criteria

1. WHEN a run completes in local mode THEN the system SHALL write JSON Lines to
   `./data/jobs/dt=YYYY-MM-DD/run.jsonl` and a CSV export under `./data/` for quick
   viewing.
2. WHEN a run completes with S3 enabled THEN the system SHALL upload the JSONL to
   `s3://{bucket}/{prefix}/jobs/dt=YYYY-MM-DD/run.jsonl`.
3. WHEN the storage mode is selected THEN it SHALL be controlled by a single
   configurable flag (local vs S3), defaulting to local.
4. WHEN writing JSONL THEN each line SHALL be one JSON object conforming to the
   output schema.
5. IF an S3 upload fails THEN the system SHALL log the error and retain the local
   copy so no data is lost.

### Requirement 6 — Polite scraping

**User Story:** As a responsible operator, I want the pipeline to be gentle on
upstream servers, so that it does not get blocked or cause harm.

#### Acceptance Criteria

1. WHEN making successive HTTP requests THEN the system SHALL wait a configurable
   delay (default 1–2 seconds) between requests.
2. WHEN making any HTTP request THEN the system SHALL send a clear, configurable
   `User-Agent` header.
3. IF a request fails with a transient error (timeout, 429, 5xx) THEN the system
   SHALL retry with exponential backoff up to a configurable maximum number of
   attempts before giving up.

### Requirement 7 — Configuration via YAML

**User Story:** As an operator, I want all tunables in one YAML file, so that I can
change behavior without editing code.

#### Acceptance Criteria

1. WHEN the pipeline starts THEN it SHALL load settings from a YAML config file.
2. WHEN config is loaded THEN it SHALL include: search keywords/roles, locations,
   `max_pages_per_run`, per-source enable flags and endpoints/params, request delay,
   retry settings, User-Agent, storage mode, local output dir, and S3
   bucket/prefix.
3. IF a required config value is missing or malformed THEN the system SHALL fail
   fast with a clear error message identifying the offending key.
4. WHEN source endpoints, query params, and pagination settings are needed THEN
   they SHALL be read from config, not hardcoded.

### Requirement 8 — Logging

**User Story:** As an operator, I want clear run logs, so that I can see what the
pipeline did.

#### Acceptance Criteria

1. WHEN a run finishes THEN the system SHALL log the number of jobs fetched, number
   new, and number skipped as duplicates.
2. WHEN a source is fetched THEN the system SHALL log per-source counts and any
   errors encountered.
3. WHEN requests are retried or rate-limited THEN the system SHALL log those events.

### Requirement 9 — Offline demo support

**User Story:** As a presenter, I want the pipeline to run offline from cached
sample responses, so that the demo works without network access.

#### Acceptance Criteria

1. WHEN an offline/sample flag is set THEN the system SHALL read source responses
   from cached fixtures in `./samples/` instead of making network calls.
2. WHEN running offline THEN the full normalize → dedupe → store flow SHALL execute
   and produce JSONL and CSV output.
3. WHEN the repository is checked out THEN at least one representative cached sample
   response per implemented source SHALL be present in `./samples/`.

### Requirement 10 — Unit tests

**User Story:** As a maintainer, I want tests for the core logic, so that
normalization and dedupe stay correct.

#### Acceptance Criteria

1. WHEN tests run THEN they SHALL cover normalization of each implemented source
   using mocked/fixture responses (no live network).
2. WHEN tests run THEN they SHALL cover deduplication (same-URL collapse and
   skip-existing behavior).
3. WHEN normalization encounters missing optional fields THEN a test SHALL assert
   those fields become `null` and the record is still produced.

### Requirement 11 — Documentation

**User Story:** As a new user, I want a short README, so that I can run the pipeline
quickly.

#### Acceptance Criteria

1. WHEN the README is read THEN it SHALL explain install, config, how to run locally,
   how to run the offline demo, and how to enable S3.

### Requirement 12 — Build order / phasing

**User Story:** As the implementer, I want the work phased, so that a working local
pipeline exists before cloud features.

#### Acceptance Criteria

1. Phase 1 SHALL deliver fetch + normalize + dedupe running locally, writing CSV and
   JSONL.
2. Phase 2 SHALL add S3 upload.
3. Phase 3 (optional) SHALL add AWS Lambda + EventBridge scheduling and SHALL NOT
   block Phases 1–2.
