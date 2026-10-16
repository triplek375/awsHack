# Job Data Collection Pipeline

Fetches job postings from HiringCafe (and optional Greenhouse/Lever/Ashby ATS
boards), normalizes them into one clean schema, dedupes on job URL, and saves the
result as date-partitioned JSON Lines plus a CSV export. Local by default, with
optional Amazon S3 upload. No scoring, notifications, or UI.

## Install

```powershell
pip install -r requirements.txt
```

## Configure

All settings live in `config.yaml` — nothing is hardcoded. Edit the `search`
section for your keywords and locations:

```yaml
search:
  keywords: ["data engineer", "cloud engineer"]
  locations: ["Texas", "remote US"]
  max_pages_per_run: 10
```

Optional ATS sources are disabled by default. Enable one by setting `enabled: true`
and adding company slugs:

```yaml
sources:
  greenhouse:
    enabled: true
    companies: ["stripe", "airbnb"]
```

## Run

Offline demo (no network — reads cached fixtures from `samples/`):

```powershell
python -m job_pipeline.cli --offline
```

Live local run (hits HiringCafe, writes to `./data/`):

```powershell
python -m job_pipeline.cli --config config.yaml --local
```

Output:

- JSONL, partitioned by date: `./data/jobs/dt=YYYY-MM-DD/run.jsonl`
- CSV for quick viewing: `./data/jobs_latest.csv`

Re-running on the same day dedupes against that day's partition, so duplicates are
never written.

## Output schema

One record per job: `url` (unique key), `title`, `company`, `location`, `remote`,
`posted_date`, `salary`, `description`, `source`, `fetched_at`. Missing optional
values are `null`.

## Enable S3 (Phase 2)

Set the bucket and switch mode in `config.yaml`:

```yaml
storage:
  mode: "s3"
  s3:
    bucket: "my-jobs-bucket"
    prefix: "raw"
```

Then run with S3 credentials configured (standard AWS env/profile):

```powershell
python -m job_pipeline.cli --config config.yaml --s3
```

The local copy is written first and retained even if the upload fails. Uploads to
`s3://{bucket}/{prefix}/jobs/dt=YYYY-MM-DD/run.jsonl`.

## Tests

```powershell
pytest
```

Tests cover normalization for each source and deduplication, all offline using the
cached fixtures in `samples/`.

## Notes

- Polite scraping: configurable delay between requests, clear User-Agent, and
  retries with exponential backoff on transient errors (429/5xx).
- HiringCafe is called through its JSON API (`POST /api/search-jobs`); no headless
  browser is required.
```
