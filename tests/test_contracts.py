"""The contracts encode accuracy rules, so the rules themselves are tested."""

import datetime as dt

import pytest
from pydantic import ValidationError

from netzanalyst.contracts import Answer, Finding, Period, QueryResult, Verdict

JULY = Period(start=dt.date(2025, 7, 1), end=dt.date(2025, 7, 31), label="July 2025")


def _result(**overrides: object) -> QueryResult:
    kwargs: dict[str, object] = {
        "sql": "SELECT 1",
        "rows": [{"n": 1}],
        "row_count": 1,
        "period": JULY,
        **overrides,
    }
    return QueryResult(**kwargs)


def test_clean_result_is_complete() -> None:
    assert _result().is_complete


def test_nulls_make_a_result_incomplete() -> None:
    """SUM() skips NULLs, so a total over them is not a whole-period figure."""
    assert not _result(null_count=3).is_complete


def test_truncation_makes_a_result_incomplete() -> None:
    assert not _result(truncated=True).is_complete


def test_a_coverage_note_makes_a_result_incomplete() -> None:
    assert not _result(coverage_note="only 12 of 31 days present").is_complete


def test_a_rejection_must_say_what_is_wrong() -> None:
    """A rejection with no reason gives the orchestrator nothing to fix."""
    with pytest.raises(ValidationError, match="at least one problem"):
        Verdict(approved=False)


def test_a_rejection_with_a_problem_is_valid() -> None:
    v = Verdict(approved=False, problems=["July total is 9,056 GWh, not 9,560 GWh"])
    assert not v.approved


def test_an_approval_needs_no_problems() -> None:
    assert Verdict(approved=True, checks_performed=["recomputed the monthly sum"]).approved


def test_an_answer_is_unverified_until_the_verifier_approves() -> None:
    answer = Answer(question="How much solar in July 2025?", text="27.6%")
    assert not answer.is_verified

    answer.verdict = Verdict(approved=False, problems=["wrong denominator"])
    assert not answer.is_verified

    answer.verdict = Verdict(approved=True)
    assert answer.is_verified


def test_findings_reject_an_invented_unit() -> None:
    with pytest.raises(ValidationError):
        Finding(value=1.0, unit="bananas", label="x", period=JULY, method="y")


def test_finding_describes_itself_with_its_period() -> None:
    f = Finding(
        value=27.6, unit="percent", label="solar share", period=JULY, method="solar / total"
    )
    assert "27.6 percent" in f.describe()
    assert "July 2025" in f.describe()
    assert "Europe/Berlin" in f.describe()
