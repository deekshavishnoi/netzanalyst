"""Generate evals/questions.jsonl with ground truth computed from the database.

Ground truth is never typed by hand. Each question ships with the SQL that
produced its answer, this script runs that SQL, and the answer is whatever the
database says. Re-running after a reload regenerates the file, so the set can
never drift from the data.

    python -m netzanalyst.evals.generate                  # write the file
    python -m netzanalyst.evals.generate --check          # verify, write nothing

The mix follows the brief: easy lookups, comparisons, trends, and traps the
system should refuse or flag rather than answer confidently.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from netzanalyst.evals.schema import Category, Expected, Question, Unit

OUTPUT = Path("evals/questions.jsonl")


@dataclass(frozen=True)
class Spec:
    """A question whose answer is computed, not asserted."""

    id: str
    question: str
    category: Category
    unit: Unit
    sql: str | None = None
    tolerance_pct: float = 1.0
    tolerance_abs: float | None = None
    value: float | None = None  # only for questions with no SQL
    text_contains: tuple[str, ...] = ()
    notes: str = ""


# --- Lookups ---------------------------------------------------------------

LOOKUPS = [
    Spec(
        id="solar-share-2025-07",
        question="How much of Germany's electricity came from solar in July 2025?",
        category="lookup",
        unit="percent",
        sql="SELECT pct_of_generation FROM v_generation_share_monthly "
        "WHERE source='solar' AND month_berlin=DATE '2025-07-01'",
        notes="The brief's own example question.",
    ),
    Spec(
        id="solar-total-2025-07",
        question="How many gigawatt-hours of solar power did Germany generate in July 2025?",
        category="lookup",
        unit="GWh",
        sql="SELECT sum(mwh)/1000 FROM v_generation_monthly "
        "WHERE source='solar' AND month_berlin=DATE '2025-07-01'",
    ),
    Spec(
        id="total-generation-2025",
        question="What was Germany's total electricity generation in 2025, in terawatt-hours?",
        category="lookup",
        unit="TWh",
        sql="SELECT sum(mwh)/1e6 FROM v_generation_monthly "
        "WHERE category <> 'storage' AND month_berlin >= DATE '2025-01-01' "
        "AND month_berlin < DATE '2026-01-01'",
        notes="Excludes pumped storage, matching how SMARD reports generation.",
    ),
    Spec(
        id="renewable-share-2025",
        question="What share of Germany's electricity generation was renewable in 2025?",
        category="lookup",
        unit="percent",
        sql="SELECT 100.0*sum(renewable_mwh)/sum(total_mwh) FROM v_renewable_share_monthly "
        "WHERE month_berlin >= DATE '2025-01-01' AND month_berlin < DATE '2026-01-01'",
    ),
    Spec(
        id="wind-onshore-2025",
        question="How much electricity did onshore wind generate in Germany in 2025, in TWh?",
        category="lookup",
        unit="TWh",
        sql="SELECT sum(mwh)/1e6 FROM v_generation_monthly WHERE source='wind_onshore' "
        "AND month_berlin >= DATE '2025-01-01' AND month_berlin < DATE '2026-01-01'",
    ),
    Spec(
        id="peak-load-2025",
        question="What was the highest hourly electricity load in Germany during 2025, in MW?",
        category="lookup",
        unit="MW",
        sql="SELECT max(mwh) FROM v_consumption WHERE metric='total_load' "
        "AND ts_berlin >= TIMESTAMP '2025-01-01 00:00' AND ts_berlin < TIMESTAMP '2026-01-01 00:00'",
    ),
    Spec(
        id="avg-price-2025",
        question="What was the average day-ahead electricity price in Germany in 2025?",
        category="lookup",
        unit="EUR/MWh",
        sql="SELECT avg(eur_per_mwh) FROM v_price WHERE bidding_zone='DE-LU' "
        "AND ts_berlin >= TIMESTAMP '2025-01-01 00:00' AND ts_berlin < TIMESTAMP '2026-01-01 00:00'",
    ),
    Spec(
        id="max-price-2025",
        question="What was the highest day-ahead electricity price in Germany in 2025?",
        category="lookup",
        unit="EUR/MWh",
        sql="SELECT max(eur_per_mwh) FROM v_price WHERE bidding_zone='DE-LU' "
        "AND ts_berlin >= TIMESTAMP '2025-01-01 00:00' AND ts_berlin < TIMESTAMP '2026-01-01 00:00'",
    ),
    Spec(
        id="biomass-2025",
        question="How much electricity came from biomass in Germany in 2025, in TWh?",
        category="lookup",
        unit="TWh",
        sql="SELECT sum(mwh)/1e6 FROM v_generation_monthly WHERE source='biomass' "
        "AND month_berlin >= DATE '2025-01-01' AND month_berlin < DATE '2026-01-01'",
    ),
    Spec(
        id="lignite-2025",
        question="How much electricity did lignite generate in Germany in 2025, in TWh?",
        category="lookup",
        unit="TWh",
        sql="SELECT sum(mwh)/1e6 FROM v_generation_monthly WHERE source='lignite' "
        "AND month_berlin >= DATE '2025-01-01' AND month_berlin < DATE '2026-01-01'",
    ),
    Spec(
        id="total-load-2025",
        question="What was Germany's total electricity consumption (grid load) in 2025, in TWh?",
        category="lookup",
        unit="TWh",
        sql="SELECT sum(mwh)/1e6 FROM v_consumption WHERE metric='total_load' "
        "AND ts_berlin >= TIMESTAMP '2025-01-01 00:00' AND ts_berlin < TIMESTAMP '2026-01-01 00:00'",
    ),
    Spec(
        id="offshore-wind-2025",
        question="How much electricity did offshore wind generate in Germany in 2025, in TWh?",
        category="lookup",
        unit="TWh",
        sql="SELECT sum(mwh)/1e6 FROM v_generation_monthly WHERE source='wind_offshore' "
        "AND month_berlin >= DATE '2025-01-01' AND month_berlin < DATE '2026-01-01'",
    ),
]

# --- Comparisons -----------------------------------------------------------

COMPARISONS = [
    Spec(
        id="solar-growth-2024-2025",
        question="By what percentage did Germany's solar generation change from 2024 to 2025?",
        category="comparison",
        unit="percent",
        tolerance_pct=2.0,
        sql="""
        WITH y AS (
          SELECT extract(year from month_berlin)::int AS yr, sum(mwh) AS mwh
          FROM v_generation_monthly WHERE source='solar'
            AND month_berlin >= DATE '2024-01-01' AND month_berlin < DATE '2026-01-01'
          GROUP BY 1)
        SELECT 100.0*(max(mwh) FILTER (WHERE yr=2025) - max(mwh) FILTER (WHERE yr=2024))
               / max(mwh) FILTER (WHERE yr=2024) FROM y
        """,
    ),
    Spec(
        id="wind-vs-solar-2025",
        question="In 2025, did wind or solar generate more electricity in Germany, and by how many TWh?",
        category="comparison",
        unit="TWh",
        sql="""
        SELECT (sum(mwh) FILTER (WHERE source IN ('wind_onshore','wind_offshore'))
              - sum(mwh) FILTER (WHERE source='solar')) / 1e6
        FROM v_generation_monthly
        WHERE month_berlin >= DATE '2025-01-01' AND month_berlin < DATE '2026-01-01'
        """,
        notes="Positive means wind generated more. Tests combining two wind sources.",
    ),
    Spec(
        id="renewable-share-change-2024-2025",
        question="How did Germany's renewable share change from 2024 to 2025, in percentage points?",
        category="comparison",
        unit="percent",
        # The change is a fraction of a percentage point, so a relative
        # tolerance would demand four-decimal accuracy. Half a point is the
        # meaningful threshold here.
        tolerance_abs=0.5,
        sql="""
        WITH y AS (
          SELECT extract(year from month_berlin)::int AS yr,
                 100.0*sum(renewable_mwh)/sum(total_mwh) AS pct
          FROM v_renewable_share_monthly
          WHERE month_berlin >= DATE '2024-01-01' AND month_berlin < DATE '2026-01-01'
          GROUP BY 1)
        SELECT max(pct) FILTER (WHERE yr=2025) - max(pct) FILTER (WHERE yr=2024) FROM y
        """,
        notes="Percentage points, not percent. Tests that the distinction is respected.",
    ),
    Spec(
        id="coal-decline-2024-2025",
        question="How much did Germany's total coal generation (lignite plus hard coal) change from 2024 to 2025, in TWh?",
        category="comparison",
        unit="TWh",
        tolerance_pct=3.0,
        sql="""
        WITH y AS (
          SELECT extract(year from month_berlin)::int AS yr, sum(mwh) AS mwh
          FROM v_generation_monthly WHERE source IN ('lignite','hard_coal')
            AND month_berlin >= DATE '2024-01-01' AND month_berlin < DATE '2026-01-01'
          GROUP BY 1)
        SELECT (max(mwh) FILTER (WHERE yr=2025) - max(mwh) FILTER (WHERE yr=2024))/1e6 FROM y
        """,
    ),
    Spec(
        id="summer-vs-winter-solar-2025",
        question="How many times more solar electricity did Germany generate in July 2025 than in January 2025?",
        category="comparison",
        unit="count",
        tolerance_pct=2.0,
        sql="""
        SELECT (max(mwh) FILTER (WHERE month_berlin=DATE '2025-07-01'))
             / (max(mwh) FILTER (WHERE month_berlin=DATE '2025-01-01'))
        FROM v_generation_monthly WHERE source='solar'
        """,
    ),
    Spec(
        id="gas-vs-coal-2025",
        question="In 2025, did natural gas or hard coal generate more electricity in Germany, and by how many TWh?",
        category="comparison",
        unit="TWh",
        sql="""
        SELECT (sum(mwh) FILTER (WHERE source='natural_gas')
              - sum(mwh) FILTER (WHERE source='hard_coal'))/1e6
        FROM v_generation_monthly
        WHERE month_berlin >= DATE '2025-01-01' AND month_berlin < DATE '2026-01-01'
        """,
    ),
]

# --- Trends ----------------------------------------------------------------

TRENDS = [
    Spec(
        id="best-solar-month-2025",
        question="Which month of 2025 had Germany's highest solar generation, and how much was it in GWh?",
        category="trend",
        unit="GWh",
        sql="SELECT max(mwh)/1000 FROM v_generation_monthly WHERE source='solar' "
        "AND month_berlin >= DATE '2025-01-01' AND month_berlin < DATE '2026-01-01'",
    ),
    Spec(
        id="negative-price-hours-2025",
        question="How many hours in 2025 had a negative day-ahead electricity price in Germany?",
        category="trend",
        unit="count",
        tolerance_pct=0.0,
        sql="SELECT count(*) FROM v_price WHERE bidding_zone='DE-LU' AND eur_per_mwh < 0 "
        "AND ts_berlin >= TIMESTAMP '2025-01-01 00:00' AND ts_berlin < TIMESTAMP '2026-01-01 00:00'",
        notes="Negative prices are real. A system that clamps them to zero answers 0 and fails.",
    ),
    Spec(
        id="highest-renewable-month-2025",
        question="Which month of 2025 had the highest renewable share in Germany, and what was it?",
        category="trend",
        unit="percent",
        sql="SELECT max(renewable_pct) FROM v_renewable_share_monthly "
        "WHERE month_berlin >= DATE '2025-01-01' AND month_berlin < DATE '2026-01-01'",
    ),
    Spec(
        id="lowest-renewable-month-2025",
        question="Which month of 2025 had the lowest renewable share in Germany, and what was it?",
        category="trend",
        unit="percent",
        sql="SELECT min(renewable_pct) FROM v_renewable_share_monthly "
        "WHERE month_berlin >= DATE '2025-01-01' AND month_berlin < DATE '2026-01-01'",
    ),
    Spec(
        id="min-solar-hour-2025",
        question="What was Germany's lowest hourly solar output during 2025, in MW?",
        category="trend",
        unit="MW",
        tolerance_pct=5.0,
        sql="SELECT min(mwh) FROM v_generation WHERE source='solar' "
        "AND ts_berlin >= TIMESTAMP '2025-01-01 00:00' AND ts_berlin < TIMESTAMP '2026-01-01 00:00'",
        notes=(
            "Solar is never exactly zero in this data: the minimum is a few MW and a "
            "typical summer night sits near 60 MW. A model reasoning from 'the sun is "
            "down, so it must be 0' answers zero and fails. The figure has to be read "
            "from the data, not inferred from how solar panels work."
        ),
    ),
    Spec(
        id="peak-solar-hour-2025",
        question="What was Germany's highest single-hour solar output in 2025, in MW?",
        category="trend",
        unit="MW",
        sql="SELECT max(mwh) FROM v_generation WHERE source='solar' "
        "AND ts_berlin >= TIMESTAMP '2025-01-01 00:00' AND ts_berlin < TIMESTAMP '2026-01-01 00:00'",
    ),
    Spec(
        id="price-below-zero-share-2025",
        question="What percentage of hours in 2025 had negative electricity prices in Germany?",
        category="trend",
        unit="percent",
        tolerance_pct=2.0,
        sql="SELECT 100.0*count(*) FILTER (WHERE eur_per_mwh < 0)/count(*) FROM v_price "
        "WHERE bidding_zone='DE-LU' AND ts_berlin >= TIMESTAMP '2025-01-01 00:00' "
        "AND ts_berlin < TIMESTAMP '2026-01-01 00:00'",
    ),
]

# --- Traps -----------------------------------------------------------------
#
# Every one of these is a real property of the data that produces a confident
# wrong answer if the system does not know about it. They are the reason the
# verifier exists. Each is documented in docs/data-sources.md.

TRAPS = [
    Spec(
        id="trap-nuclear-2025",
        question="How much nuclear power did Germany generate in 2025?",
        category="trap",
        unit="TWh",
        value=0.0,
        text_contains=("shut down", "2023"),
        notes=(
            "Germany shut its last three reactors on 15 April 2023 and the SMARD series "
            "ends January 2024. The answer is zero BECAUSE THE PLANTS ARE GONE, not "
            "'no data found'. A system that says 'no data' has failed to explain."
        ),
    ),
    Spec(
        id="trap-nuclear-2026",
        question="What was Germany's nuclear generation in the first half of 2026?",
        category="trap",
        unit="TWh",
        value=0.0,
        text_contains=("shut down", "nuclear"),
        notes="Same trap, later period, to check the explanation is not memorised for 2025 alone.",
    ),
    Spec(
        id="trap-pumped-storage-renewable",
        question="Is pumped storage counted as renewable generation in Germany's renewable share?",
        category="trap",
        unit="text",
        text_contains=("not", "storage"),
        notes=(
            "No. SMARD and Fraunhofer ISE exclude pumped storage from the share "
            "denominator. Counting it inflates the renewable figure."
        ),
    ),
    Spec(
        id="trap-future-2030",
        question="How much solar power did Germany generate in 2030?",
        category="trap",
        unit="TWh",
        value=None,
        text_contains=("future", "no data"),
        notes="A future date. The system must refuse, not extrapolate or hallucinate.",
    ),
    Spec(
        id="trap-before-coverage-2019",
        question="What was Germany's renewable share in 2019?",
        category="trap",
        unit="percent",
        value=None,
        text_contains=("2024", "not"),
        notes=(
            "Before the loaded range, which starts 2024-01-01. The system must check "
            "v_data_coverage and say the period is not loaded, rather than answering "
            "from whatever rows happen to exist."
        ),
    ),
    Spec(
        id="trap-partial-current-month",
        question="What was Germany's total electricity generation in September 2026?",
        category="trap",
        unit="TWh",
        value=None,
        text_contains=("partial", "incomplete"),
        notes=(
            "The data stops mid-September 2026, so any total is a partial month. The "
            "system must flag that rather than reporting it as a full month. This is the "
            "most realistic failure of the set: the number looks perfectly plausible."
        ),
    ),
    Spec(
        id="trap-negative-price-is-real",
        question="Germany's electricity price went negative in 2025. Was that a data error?",
        category="trap",
        unit="text",
        text_contains=("not", "normal"),
        notes=(
            "No. Negative day-ahead prices are normal in hours of high wind and solar. "
            "A system that treats them as errors will clamp or discard real data."
        ),
    ),
    Spec(
        id="trap-france-data",
        question="How much electricity did France generate from nuclear in 2025?",
        category="trap",
        unit="TWh",
        value=None,
        text_contains=("Germany", "not"),
        notes="Out of scope: this database covers Germany. Must decline, not invent.",
    ),
]

ALL_SPECS = LOOKUPS + COMPARISONS + TRENDS + TRAPS


def _connect() -> Any:
    try:
        import psycopg
    except ImportError:
        sys.exit("psycopg is not installed. Run: pip install -e '.[dev]'")
    url = os.environ.get("DATABASE_URL")
    if not url:
        sys.exit("DATABASE_URL is not set. Run: set -a; . ./.env; set +a")
    return psycopg.connect(url)


def build(check_only: bool = False) -> int:
    conn = _connect()
    questions: list[Question] = []
    failures: list[str] = []

    try:
        for spec in ALL_SPECS:
            value = spec.value
            if spec.sql:
                with conn.cursor() as cur:
                    cur.execute(spec.sql)
                    row = cur.fetchone()
                if row is None or row[0] is None:
                    failures.append(f"{spec.id}: ground-truth SQL returned no value")
                    continue
                value = round(float(row[0]), 4)

            questions.append(
                Question(
                    id=spec.id,
                    question=spec.question,
                    category=spec.category,
                    expected=Expected(
                        value=value,
                        unit=spec.unit,
                        tolerance_pct=spec.tolerance_pct,
                        tolerance_abs=spec.tolerance_abs,
                        text_contains=list(spec.text_contains),
                    ),
                    ground_truth_sql=" ".join(spec.sql.split()) if spec.sql else None,
                    notes=spec.notes,
                )
            )
    finally:
        conn.close()

    if failures:
        for f in failures:
            print(f"  FAIL {f}", file=sys.stderr)
        print(f"\n{len(failures)} question(s) could not be grounded.", file=sys.stderr)
        return 1

    by_category: dict[str, int] = {}
    for q in questions:
        by_category[q.category] = by_category.get(q.category, 0) + 1

    print(f"{len(questions)} questions grounded against the database")
    for category, count in sorted(by_category.items()):
        print(f"  {category:12} {count}")

    if check_only:
        print("\n--check: nothing written")
        return 0

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT.open("w", encoding="utf-8") as fh:
        for q in questions:
            fh.write(json.dumps(q.model_dump(), ensure_ascii=False) + "\n")
    print(f"\nwrote {OUTPUT}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--check", action="store_true", help="verify grounding, write nothing")
    args = ap.parse_args(argv)
    return build(check_only=args.check)


if __name__ == "__main__":
    sys.exit(main())
