"""Score jobs by how well their text overlaps with the resume skill profile.

The score is a weighted count of distinct resume skills found in the job's
title + description, normalized to 0-100 against the best achievable score for
the configured profile. Technical skills can be weighted higher than generic
business terms so a genuine tech match outranks a buzzword match.
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

from .models import JobRecord


def _compile_skill_patterns(skills: List[str]) -> Dict[str, re.Pattern]:
    """Build whole-word, case-insensitive regexes for each skill.

    Multi-word skills (e.g. "Apache Airflow") match as a phrase with flexible
    whitespace. Special characters in skills (e.g. "C++") are escaped. Short
    all-caps skills still match on word boundaries so "SQL" won't match inside
    another word.
    """
    patterns: Dict[str, re.Pattern] = {}
    for skill in skills:
        skill = skill.strip()
        if not skill:
            continue
        # Escape regex specials, then allow flexible whitespace between tokens.
        escaped = re.escape(skill)
        escaped = re.sub(r"\\\s+", r"\\s+", escaped)
        patterns[skill] = re.compile(rf"(?<!\w){escaped}(?!\w)", re.IGNORECASE)
    return patterns


class ResumeScorer:
    """Scores JobRecords against a resume skill profile."""

    def __init__(
        self,
        skills: List[str],
        weights: Dict[str, float] | None = None,
        default_weight: float = 1.0,
    ) -> None:
        self.skills = [s for s in skills if s and s.strip()]
        self.default_weight = default_weight
        # Case-insensitive weight lookup.
        self._weights = {k.lower(): float(v) for k, v in (weights or {}).items()}
        self._patterns = _compile_skill_patterns(self.skills)
        # Best achievable raw score = sum of every skill's weight.
        self._max_raw = sum(self._weight_for(s) for s in self.skills) or 1.0

    def _weight_for(self, skill: str) -> float:
        return self._weights.get(skill.lower(), self.default_weight)

    def score_text(self, text: str) -> Tuple[float, List[str]]:
        """Return (score_0_100, matched_skills) for a block of text."""
        if not text:
            return 0.0, []
        matched: List[str] = []
        raw = 0.0
        for skill, pattern in self._patterns.items():
            if pattern.search(text):
                matched.append(skill)
                raw += self._weight_for(skill)
        score = round(100.0 * raw / self._max_raw, 1)
        return score, matched

    def score_record(self, rec: JobRecord) -> JobRecord:
        """Attach match_score and matched_skills to a record (in place)."""
        text = " ".join(filter(None, [rec.title, rec.description]))
        score, matched = self.score_text(text)
        rec.match_score = score
        rec.matched_skills = matched
        return rec


def score_and_rank(
    records: List[JobRecord],
    scorer: ResumeScorer,
    min_score: float,
) -> Tuple[List[JobRecord], int]:
    """Score every record, drop those below min_score, sort highest-first.

    Returns (ranked_kept_records, num_dropped_below_threshold).
    """
    for rec in records:
        scorer.score_record(rec)
    kept = [r for r in records if (r.match_score or 0.0) >= min_score]
    dropped = len(records) - len(kept)
    kept.sort(key=lambda r: r.match_score or 0.0, reverse=True)
    return kept, dropped
