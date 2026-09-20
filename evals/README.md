# Evaluation set

`questions.jsonl` holds 33 questions with known answers. **The answers are never
typed by hand.** Each question ships with the SQL that produced it, and the
generator runs that SQL against the database:

```bash
set -a; . ./.env; set +a
python -m netzanalyst.evals.generate          # regenerate
python -m netzanalyst.evals.generate --check  # verify, write nothing
```

Re-running after a data reload regenerates the file, so the set cannot drift
away from the data it grades against.

## The mix

| Category | Count | What it tests |
|---|---:|---|
| `lookup` | 12 | Single figures: totals, shares, peaks, averages |
| `comparison` | 6 | Two periods or two sources, including percent vs percentage points |
| `trend` | 7 | Extremes over time, counts of hours, minima |
| `trap` | 8 | Questions that produce confident wrong answers |

## The traps

Each one is a real property of the data, documented in
[docs/data-sources.md](../docs/data-sources.md), that yields a plausible wrong
answer if the system does not know about it. They are why the verifier exists.

| Question | The failure it catches |
|---|---|
| Nuclear in 2025 / H1 2026 | Answer is **zero because the reactors are gone** (shut down April 2023), not "no data found". Two periods, so the explanation cannot be memorised for one date. |
| Is pumped storage renewable? | No. Counting it inflates the renewable share. |
| Solar in 2030 | A future date. Must refuse, not extrapolate. |
| Renewable share in 2019 | Before the loaded range. Must check `v_data_coverage`, not answer from whatever rows exist. |
| Generation in September 2026 | **Partial month.** The most realistic failure in the set: the number looks entirely plausible. |
| Were negative prices an error? | No, they are normal in windy, sunny hours. |
| France's nuclear generation | Out of scope. Must decline, not invent. |

## Two questions worth knowing about

**`min-solar-hour-2025`** answers 4 MW. Solar in this data is *never exactly
zero* — a typical summer night sits near 60 MW. A model reasoning "the sun is
down, so it must be 0" fails. The figure has to be read, not inferred.

**`renewable-share-change-2024-2025`** uses `tolerance_abs`, not a percentage.
The change is 0.27 percentage points, and a ±5% relative tolerance would demand
±0.013 — effectively exact. Answers near zero need an absolute tolerance.

## Scoring

`tolerance_pct` defaults to ±1%, per the brief. `tolerance_abs` overrides it
where relative tolerance is meaningless. Traps with `value: null` are only
satisfied by a refusal: **answering `0` to an unanswerable question is wrong**,
and answering `null` to a genuine zero is also wrong. Those two cases are
distinct and separately tested.

Results land in `results/`, committed to the repo as the brief requires.
