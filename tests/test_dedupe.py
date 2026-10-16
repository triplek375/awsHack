"""Dedup tests: same-url collapse and skip-existing behavior."""

from job_pipeline.dedupe import dedupe_on_url, filter_existing
from job_pipeline.models import JobRecord


def _rec(url):
    return JobRecord(url=url, source="test", fetched_at="2026-10-16T00:00:00+00:00")


def test_dedupe_on_url_collapses_duplicates():
    records = [_rec("a"), _rec("b"), _rec("a"), _rec("c"), _rec("b")]
    unique, dropped = dedupe_on_url(records)
    assert [r.url for r in unique] == ["a", "b", "c"]
    assert dropped == 2


def test_dedupe_keeps_first_occurrence():
    first = _rec("a")
    first.title = "first"
    second = _rec("a")
    second.title = "second"
    unique, dropped = dedupe_on_url([first, second])
    assert len(unique) == 1
    assert unique[0].title == "first"
    assert dropped == 1


def test_filter_existing_skips_persisted_urls():
    records = [_rec("a"), _rec("b"), _rec("c")]
    existing = {"a", "c"}
    new, skipped = filter_existing(records, existing)
    assert [r.url for r in new] == ["b"]
    assert skipped == 2


def test_filter_existing_empty_set_keeps_all():
    records = [_rec("a"), _rec("b")]
    new, skipped = filter_existing(records, set())
    assert len(new) == 2
    assert skipped == 0
