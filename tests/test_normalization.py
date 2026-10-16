"""Normalization tests for each source using cached sample responses."""

from job_pipeline.config import AtsConfig, HiringCafeConfig, SearchConfig
from job_pipeline.sources.ashby import AshbySource
from job_pipeline.sources.greenhouse import GreenhouseSource
from job_pipeline.sources.hiring_cafe import HiringCafeSource
from job_pipeline.sources.lever import LeverSource
from job_pipeline.models import SCHEMA_FIELDS


def _assert_schema(rec):
    d = rec.to_dict()
    assert list(d.keys()) == SCHEMA_FIELDS
    assert d["url"]  # required
    assert d["source"]
    assert d["fetched_at"]


def test_hiring_cafe_normalization(hiring_cafe_sample, fake_http):
    http = fake_http(hiring_cafe_sample)
    search = SearchConfig(
        keywords=["data engineer"], locations=["Texas"], max_pages_per_run=3
    )
    src = HiringCafeSource(HiringCafeConfig(page_size=100), search, http)
    records = list(src.fetch())

    # 3 raw rows, one is a duplicate url (dedupe happens later), so 3 records.
    assert len(records) == 3
    first = records[0]
    _assert_schema(first)
    assert first.title == "Data Engineer"
    assert first.company == "Example Co"
    assert first.remote is True
    assert first.salary == "USD 120000-160000"
    assert "data pipelines" in first.description
    # Second posting is onsite in Austin, TX -> remote False.
    assert records[1].remote is False


def test_greenhouse_normalization(greenhouse_sample, fake_http):
    http = fake_http(greenhouse_sample)
    cfg = AtsConfig(
        enabled=True,
        url_template="https://boards-api.greenhouse.io/v1/boards/{company}/jobs?content=true",
        companies=["examplecorp"],
    )
    records = list(GreenhouseSource(cfg, http).fetch())
    assert len(records) == 2
    _assert_schema(records[0])
    assert records[0].company == "examplecorp"
    assert records[0].remote is True
    # Greenhouse provides no salary -> null.
    assert records[0].salary is None
    assert records[1].remote is False


def test_lever_normalization(lever_sample, fake_http):
    http = fake_http(lever_sample)
    cfg = AtsConfig(
        enabled=True,
        url_template="https://api.lever.co/v0/postings/{company}?mode=json",
        companies=["examplelever"],
    )
    records = list(LeverSource(cfg, http).fetch())
    assert len(records) == 2
    _assert_schema(records[0])
    assert records[0].title == "Data Engineer"
    assert records[0].remote is True
    assert records[1].remote is False


def test_ashby_normalization(ashby_sample, fake_http):
    http = fake_http(ashby_sample)
    cfg = AtsConfig(
        enabled=True,
        url_template="https://api.ashbyhq.com/posting-api/job-board/{company}",
        companies=["exampleashby"],
    )
    records = list(AshbySource(cfg, http).fetch())
    assert len(records) == 2
    _assert_schema(records[0])
    assert records[0].remote is True
    assert records[0].salary == "USD 130K - 170K"
    # Second has no compensation -> null salary.
    assert records[1].salary is None


def test_missing_optional_fields_become_null(fake_http):
    """A minimal posting still produces a record with null optionals."""
    payload = {
        "results": [
            {"apply_url": "https://x.co/jobs/1", "job_information": {}, "v5_processed_job_data": {}}
        ]
    }
    http = fake_http(payload)
    search = SearchConfig(keywords=["x"], locations=["y"], max_pages_per_run=1)
    src = HiringCafeSource(HiringCafeConfig(page_size=100), search, http)
    records = list(src.fetch())
    assert len(records) == 1
    rec = records[0]
    assert rec.url == "https://x.co/jobs/1"
    assert rec.title is None
    assert rec.salary is None
    assert rec.posted_date is None
