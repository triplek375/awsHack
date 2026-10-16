"""Tests for resume skill scoring and ranking."""

from job_pipeline.models import JobRecord
from job_pipeline.scoring import ResumeScorer, score_and_rank


SKILLS = ["Python", "SQL", "AWS", "Apache Airflow", "Docker", "Agile"]
WEIGHTS = {"Python": 3.0, "SQL": 3.0, "Apache Airflow": 3.0, "AWS": 2.5}


def _rec(url, title=None, description=None):
    return JobRecord(
        url=url,
        source="greenhouse",
        fetched_at="2026-10-16T00:00:00+00:00",
        title=title,
        description=description,
    )


def test_matches_skills_whole_word_case_insensitive():
    scorer = ResumeScorer(SKILLS, WEIGHTS)
    score, matched = scorer.score_text("We use python and sql on AWS daily.")
    assert set(matched) == {"Python", "SQL", "AWS"}
    assert score > 0


def test_multi_word_skill_phrase_match():
    scorer = ResumeScorer(SKILLS, WEIGHTS)
    _, matched = scorer.score_text("Pipelines orchestrated with Apache   Airflow.")
    assert "Apache Airflow" in matched


def test_no_substring_false_positive():
    # "SQL" must not match inside "NoSQL"/"MySQLish"; "AWS" not in "awesome".
    scorer = ResumeScorer(["SQL", "AWS"], {})
    _, matched = scorer.score_text("An awesome MySQLish datastore.")
    assert matched == []


def test_higher_weighted_skill_scores_higher():
    scorer = ResumeScorer(SKILLS, WEIGHTS)
    python_score, _ = scorer.score_text("Strong Python experience.")
    agile_score, _ = scorer.score_text("Strong Agile experience.")
    assert python_score > agile_score


def test_score_is_zero_for_no_match_and_empty_text():
    scorer = ResumeScorer(SKILLS, WEIGHTS)
    assert scorer.score_text("")[0] == 0.0
    assert scorer.score_text("Purely unrelated marketing copy.")[0] == 0.0


def test_score_record_populates_fields():
    scorer = ResumeScorer(SKILLS, WEIGHTS)
    rec = _rec("u1", title="Data Engineer", description="Python, SQL, Docker.")
    scorer.score_record(rec)
    assert rec.match_score > 0
    assert set(rec.matched_skills) == {"Python", "SQL", "Docker"}


def test_score_and_rank_filters_and_sorts():
    scorer = ResumeScorer(SKILLS, WEIGHTS)
    strong = _rec("strong", title="DE", description="Python SQL AWS Apache Airflow Docker")
    weak = _rec("weak", title="PM", description="Agile only")
    none = _rec("none", title="Sales", description="cold calling and quotas")
    kept, dropped = score_and_rank([weak, strong, none], scorer, min_score=10.0)
    # Strong is kept and ranked first; none is dropped.
    assert kept[0].url == "strong"
    assert "none" not in [r.url for r in kept]
    assert dropped >= 1
    # Kept list is sorted descending by score.
    scores = [r.match_score for r in kept]
    assert scores == sorted(scores, reverse=True)


def test_matched_skills_serialized_as_csv_string():
    scorer = ResumeScorer(SKILLS, WEIGHTS)
    rec = _rec("u1", description="Python and SQL")
    scorer.score_record(rec)
    d = rec.to_dict()
    assert isinstance(d["matched_skills"], str)
    assert "Python" in d["matched_skills"]
