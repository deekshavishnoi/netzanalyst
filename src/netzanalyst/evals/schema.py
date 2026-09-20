"""Schema for the evaluation question set.

Every question carries its own ground truth AND the SQL that produced it, so
the answers can be regenerated and re-verified rather than trusted. A question
set whose answers cannot be recomputed rots silently as the data is reloaded.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Category = Literal["lookup", "comparison", "trend", "trap"]
Unit = Literal["MWh", "GWh", "TWh", "MW", "EUR/MWh", "percent", "count", "text"]


class Expected(BaseModel):
    """The correct answer, and how close counts as correct."""

    model_config = ConfigDict(extra="forbid")

    value: float | None = Field(
        None,
        description="Numeric answer. None when the correct response is a refusal or an explanation.",
    )
    unit: Unit
    tolerance_pct: float = Field(
        1.0,
        ge=0,
        description="Relative tolerance in percent. The brief's default is +/-1%.",
    )
    tolerance_abs: float | None = Field(
        None,
        ge=0,
        description=(
            "Absolute tolerance, used instead of tolerance_pct when set. Required for "
            "answers near zero, where a relative tolerance collapses to nothing: a "
            "0.27 percentage-point change at +/-5% would demand +/-0.013."
        ),
    )
    text_contains: list[str] = Field(
        default_factory=list,
        description="Phrases the answer must convey. Used for traps where the point is the reasoning.",
    )

    def matches(self, actual: float | None) -> bool:
        """Whether a numeric answer is within tolerance."""
        if self.value is None:
            return actual is None
        if actual is None:
            return False
        if self.tolerance_abs is not None:
            return abs(actual - self.value) <= self.tolerance_abs
        if self.value == 0:
            return abs(actual) < 1e-9
        return abs(actual - self.value) / abs(self.value) * 100 <= self.tolerance_pct


class Question(BaseModel):
    """One evaluation question."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(..., pattern=r"^[a-z0-9-]+$")
    question: str
    category: Category
    expected: Expected
    ground_truth_sql: str | None = Field(
        None,
        description="The query that produced expected.value. None for questions with no numeric answer.",
    )
    notes: str = Field("", description="Why this question is in the set, and what it tests.")

    @property
    def is_trap(self) -> bool:
        return self.category == "trap"
