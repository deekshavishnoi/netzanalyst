# Progress log

One entry per work session: what was done, what broke, what is next.

---

## 2026-09-20 — Session 1: data layer and MCP server

**Done**

- Scaffolded the repo to the structure in the brief, `git init` on `main`.
- Verified both data sources live before writing any code against them:
  - SMARD `chart_data` endpoints return `{meta_data, series: [[epoch_ms, value]]}`,
    168 hourly points per weekly chunk.
  - Energy-Charts API is at **v2** with a different response shape from v1
    (`data: [{timestamp, values}]`, not `unix_seconds` + `production_types`).
    Code is written against v2 and the shape is checked at runtime.
- Confirmed the SMARD filter-ID map from
  [bundesAPI/smard-api](https://github.com/bundesAPI/smard-api) and sanity-checked
  magnitudes: load 36–63 GW, solar 0 at night peaking 44 GW, prices −2 to 697 EUR/MWh.
- Postgres schema (`sql/001_schema.sql`): 5 tables, 8 views, column comments that
  `get_schema` surfaces to the agents.
- Local Postgres 16.15 via Homebrew, database created, read-only role
  `netzanalyst_ro` verified to reject both writes and DDL.
- `scripts/setup-local-db.sh` makes that setup reproducible in one command.
- `data/ingest/smard.py`: shape-checked, range-checked, idempotent loader.
  Loading 2024-01-01 → 2026-09-19, ~23,832 rows per series across 16 series.
- TypeScript MCP server with all three tools, working over streamable HTTP:
  `get_schema`, `run_sql`, `fetch_energy_charts`. Verified with real MCP
  protocol calls (initialize → tools/list → tools/call).
- 19 unit tests on the SQL guard, all passing, including injection attempts
  hidden in comments, string literals and dollar-quoted blocks.

**What broke**

- Python from python.org has no usable CA bundle on macOS, so every HTTPS call
  failed with `CERTIFICATE_VERIFY_FAILED`. Fixed inside the script by building
  the SSL context from `certifi` when it is importable, rather than patching
  Dee's Python install — this also makes the repo work on a stock machine.
- First ingest run died with `permission denied for table generation`: the
  schema had been applied as a superuser, so the `netzanalyst` ingest role did
  not own the tables. Fixed, and `scripts/setup-local-db.sh` now applies the
  schema **as the owner** so it cannot recur.
- `node-postgres` turned a DATE into a JS Date and serialised it in UTC, so
  `2025-06-01` reached the agent as `"2025-05-31T22:00:00.000Z"` — June's number
  labelled as May. Fixed with explicit type parsers that pass Postgres's own
  text through untouched. This one would have quietly produced wrong answers.
- Off-by-one in the ingest date filter: an inclusive upper bound returned 169
  rows for a 7-day window instead of 168. Now half-open.

**Decisions**

- **MCP package:** the SDK was split since the brief was written.
  `@modelcontextprotocol/sdk` (v1.30.0, the brief's choice) is the pre-split
  package; `@modelcontextprotocol/server` v2 from the same official repo is
  current and actively released. Dee chose v2. The API is
  `createMcpHandler` + `registerTool` with zod v4 schemas.
- **Local Postgres:** Homebrew rather than Docker Desktop, to get moving without
  an admin install. `docker-compose.yml` is still the documented path in the
  README and needs testing once Docker is available.

**Next**

1. Finish and verify the full ingest; spot-check totals against SMARD's website.
2. Point an MCP client (Claude Desktop or MCP Inspector) at the server and take
   the **"MCP server tools listed in an MCP client"** screenshot.
3. Write `evals/questions.jsonl` — the data caveats in `data/README.md` are
   ready-made trick questions (nuclear after 2024, pumped storage, negative prices).
4. Terraform skeleton, `terraform plan` only, nothing applied.
5. **Dee's day-one Azure checks** (blocking for Week 2): confirm `gpt-5.4-mini`
   can be deployed and a hosted agent created on the trial; set budget alerts at
   $50 / $100 / $150; fill in the trial start and end dates in the brief.

**Open questions for Dee**

- Trial start/end dates are still blank in the brief. Everything has to land
  before the earlier of the trial end and 23 Oct.
- Model names `gpt-5.4-mini` / `gpt-5.4` are taken from the brief and have not
  been checked against what the trial can actually deploy. That is the day-one
  check above — if they are unavailable, tell me and we re-plan the model choice.
