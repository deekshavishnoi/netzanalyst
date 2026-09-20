"""Typed hand-offs between agents.

The orchestrator, SQL agent, analysis agent and verifier pass structured
objects rather than prose. Three reasons this matters here:

1. **The verifier needs the evidence, not a summary.** It can only re-check a
   number if it receives the rows that produced it, the SQL that fetched them,
   and the period they cover. A free-text hand-off loses exactly that.
2. **Silent nulls are the main accuracy risk.** `SUM()` skips NULLs, so a total
   can look complete when it is not. `null_count` and `is_complete` travel with
   every result so no agent has to remember to ask.
3. **Evals need structure.** Scoring 50 questions automatically means reading
   a field, not parsing English.
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Period(BaseModel):
    """A time range in Berlin local time, which is how questions are asked."""

    model_config = ConfigDict(extra="forbid")

    start: dt.date
    end: dt.date = Field(..., description="Inclusive end date.")
    label: str = Field(..., description="Human phrasing, e.g. 'July 2025'.")

    def describe(self) -> str:
        return f"{self.label} ({self.start.isoformat()} to {self.end.isoformat()}, Europe/Berlin)"


class QueryResult(BaseModel):
    """Rows from the SQL agent, with everything the verifier needs to re-check."""

    model_config = ConfigDict(extra="forbid")

    sql: str = Field(..., description="The exact query that ran.")
    rows: list[dict[str, Any]]
    row_count: int
    period: Period | None = None
    source: Literal["database", "energy_charts"] = "database"

    null_count: int = Field(
        0, description="Values that were NULL. SUM() skips these, so a total can look complete."
    )
    truncated: bool = Field(False, description="True if the row cap cut the result off.")
    coverage_note: str | None = Field(
        None,
        description="Set when the data does not fully span the period asked about.",
    )

    @property
    def is_complete(self) -> bool:
        """Whether this result can be reported as a whole-period figure."""
        return not self.truncated and self.null_count == 0 and self.coverage_note is None


class Finding(BaseModel):
    """One computed number, with the arithmetic that produced it."""

    model_config = ConfigDict(extra="forbid")

    value: float
    unit: Literal["MWh", "GWh", "TWh", "MW", "EUR/MWh", "percent"]
    label: str = Field(..., description="What this number is, e.g. 'solar share of generation'.")
    period: Period
    method: str = Field(
        ...,
        description="How it was computed, plainly enough for the verifier to redo it.",
    )
    rounded_to: int | None = Field(None, description="Decimal places, if rounded.")

    def describe(self) -> str:
        return f"{self.label}: {self.value} {self.unit} over {self.period.describe()}"


class Analysis(BaseModel):
    """What the analysis agent returns."""

    model_config = ConfigDict(extra="forbid")

    headline: Finding
    supporting: list[Finding] = Field(default_factory=list)
    chart_path: str | None = None
    caveats: list[str] = Field(
        default_factory=list,
        description="Missing data, partial periods, anything that qualifies the number.",
    )


class Verdict(BaseModel):
    """The verifier's decision. The last gate before the user sees an answer."""

    model_config = ConfigDict(extra="forbid")

    approved: bool
    problems: list[str] = Field(
        default_factory=list,
        description="Each specific problem found. Must be non-empty when rejected.",
    )
    corrected_values: dict[str, float] = Field(
        default_factory=dict,
        description="Correct value per label, where the verifier could determine it.",
    )
    checks_performed: list[str] = Field(
        default_factory=list,
        description="What was actually checked, so an unverified approval is visible.",
    )

    def model_post_init(self, _context: object) -> None:
        # A rejection with no stated problem gives the orchestrator nothing to
        # act on, and would loop forever.
        if not self.approved and not self.problems:
            raise ValueError("A rejected verdict must list at least one problem.")


class Answer(BaseModel):
    """The final user-facing answer, assembled by the orchestrator."""

    model_config = ConfigDict(extra="forbid")

    question: str
    text: str
    headline: Finding | None = None
    chart_path: str | None = None
    sources: list[str] = Field(
        default_factory=lambda: ["SMARD (Bundesnetzagentur), CC BY 4.0"],
    )
    verdict: Verdict | None = None
    caveats: list[str] = Field(default_factory=list)

    # Recorded for the eval report: cost and latency per question, and which
    # prompt revisions produced this answer.
    prompt_versions: dict[str, str] = Field(default_factory=dict)
    total_tokens: int | None = None
    latency_ms: int | None = None

    @property
    def is_verified(self) -> bool:
        return self.verdict is not None and self.verdict.approved
