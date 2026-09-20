"""The eval question set itself is tested: a bad question set scores nothing."""

import json
from pathlib import Path

import pytest

from netzanalyst.evals.schema import Expected, Question

QUESTIONS_FILE = Path("evals/questions.jsonl")


def load_questions() -> list[Question]:
    if not QUESTIONS_FILE.exists():
        pytest.skip("evals/questions.jsonl not generated yet")
    return [
        Question.model_validate(json.loads(line))
        for line in QUESTIONS_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def test_question_set_meets_the_briefs_size() -> None:
    assert 30 <= len(load_questions()) <= 50


def test_ids_are_unique() -> None:
    ids = [q.id for q in load_questions()]
    assert len(ids) == len(set(ids))


def test_every_category_is_represented() -> None:
    """The brief: easy lookups, comparisons, trends, and a few trick questions."""
    categories = {q.category for q in load_questions()}
    assert categories == {"lookup", "comparison", "trend", "trap"}


def test_numeric_questions_carry_the_sql_that_produced_them() -> None:
    """Ground truth must be reproducible, not asserted by hand."""
    for q in load_questions():
        if q.expected.value is not None and not q.is_trap:
            assert q.ground_truth_sql, f"{q.id} has a value but no SQL to reproduce it"


def test_every_trap_explains_itself() -> None:
    """A trap without a note is unmaintainable six weeks later."""
    for q in load_questions():
        if q.is_trap:
            assert len(q.notes) > 40, f"{q.id} needs a note explaining the trap"


def test_traps_require_reasoning_not_just_a_number() -> None:
    """The point of a trap is the explanation, so each demands specific phrases."""
    for q in load_questions():
        if q.is_trap:
            assert q.expected.text_contains, f"{q.id} must require explanatory phrases"


def test_near_zero_answers_use_an_absolute_tolerance() -> None:
    """A relative tolerance collapses to nothing near zero."""
    for q in load_questions():
        v = q.expected.value
        if v is not None and 0 < abs(v) < 1.0:
            assert q.expected.tolerance_abs is not None, (
                f"{q.id} expects {v}, which needs tolerance_abs; a relative "
                f"tolerance would demand near-exact accuracy"
            )


def test_tolerance_matching() -> None:
    within = Expected(value=100.0, unit="GWh", tolerance_pct=1.0)
    assert within.matches(100.5)
    assert not within.matches(102.0)


def test_absolute_tolerance_overrides_relative() -> None:
    e = Expected(value=0.27, unit="percent", tolerance_pct=1.0, tolerance_abs=0.5)
    assert e.matches(0.6), "0.6 is within 0.5 absolute of 0.27"
    assert not e.matches(1.0)


def test_a_refusal_is_only_matched_by_a_refusal() -> None:
    """Traps with value=None expect no number at all."""
    e = Expected(value=None, unit="TWh")
    assert e.matches(None)
    assert not e.matches(0.0), "answering 0 to an unanswerable question is wrong"


def test_zero_is_distinct_from_no_answer() -> None:
    """Nuclear in 2025 is genuinely zero, not unanswerable."""
    e = Expected(value=0.0, unit="TWh")
    assert e.matches(0.0)
    assert not e.matches(None)
