# Progress log

One entry per work session. Each entry records what was built, **what broke and
how it was diagnosed**, and **what each claim was verified against** — the
source, the check, and the result. The failures are kept deliberately: they are
the most useful part to read back.

---

# Session 1 — 2026-09-20

Goal: Week 1 of the build plan — data, infrastructure, MCP server.

## 1. Environment check

**Checked first, before writing anything.**

| Tool | Result |
|---|---|
| node | v22.23.2 |
| npm | 10.9.8 |
| python3 | 3.10.11 (python.org build) |
| git | 2.50.1 |
| gh | 2.99.0 |
| **docker** | **not installed** |
| **terraform** | **not installed** |
| **psql** | **not installed** |
| **az** | **not installed** |
| brew | 7.0.3 — available |

Four of the brief's assumed tools were missing. Rather than guess, this became a
decision point: Homebrew Postgres (fast, no admin) vs Docker Desktop (matches
the brief exactly, needs a GUI install). **Dee chose Homebrew Postgres**, with
`docker-compose.yml` still shipped as the documented portable path.

## 2. Verifying the data sources before writing code against them

The brief names SMARD and Energy-Charts. Neither was taken on trust.

### SMARD

- **Claim checked:** is there an API, and what shape is it?
- **Source:** web search → [bundesAPI/smard-api](https://github.com/bundesAPI/smard-api),
  then the live endpoints directly.
- **Result:** there is **no official documented API**. The `chart_data`
  endpoints are what smard.de's own front-end calls. This is a real project risk
  and is now written down in `docs/data-sources.md` and the README, with the
  manual CSV download centre named as the fallback.

```
GET /app/chart_data/1223/DE/index_hour.json
  -> 612 weekly timestamps, 2014-12-28 .. 2026-09-13
GET /app/chart_data/1223/DE/1223_DE_hour_1788732000000.json
  -> {"meta_data": {...}, "series": [[epoch_ms, value|null] x168]}
```

> **First mistake.** I constructed a data URL from a timestamp I invented rather
> than one from the index, and got **HTTP 404**. The index is not decoration —
> the week-start timestamps are the only valid keys. Fixed by always reading
> `index_hour.json` first, which is what the loader now does.

> **Second mistake, caught by cross-checking.** A search result claimed filter
> `1223` was "actual load". The authoritative `openapi.yaml` in the bundesAPI
> repo says `1223` is **lignite**. The data settled it: filter 1223 returns
> 8–11 GW, and German load runs 35–65 GW. **Never take a filter-ID mapping from
> a search snippet.** The full verified map is in `docs/data-sources.md`.

**Magnitude sanity check** — one week of hourly data per filter, against what
these series should physically look like:

| Filter | Series | min | max | mean | Verdict |
|---|---|---:|---:|---:|---|
| 410 | Total load | 35,946 | 63,477 | 51,091 | ✅ German load is ~35–70 GW |
| 4068 | Solar | 0.0 | 44,365 | 11,340 | ✅ zero at night, ~44 GW peak |
| 4067 | Wind onshore | 545 | 25,736 | 10,215 | ✅ plausible range |
| 4169 | Price DE-LU | −2.0 | 697.3 | 135.3 | ✅ **negative prices are real** |

### Energy-Charts

- **Claim checked:** the endpoint shape.
- **Source:** the live OpenAPI spec at `https://api.energy-charts.info/openapi.json`.
- **Result:** the API is at **v2**, and the v2 response shape is **different
  from v1**. v1 returns `unix_seconds` + `production_types`; v2 returns
  `data: [{timestamp, values}]` plus a `series` index and an explicit `license`
  field. Code written from memory of v1 would have failed at runtime. Written
  against v2, with a runtime shape check.

### Licences

- SMARD: **CC BY 4.0** — confirmed on the download centre page.
- Energy-Charts: **CC BY 4.0** — returned in the body of every API response.
- Both attributions are in the README, `docs/data-sources.md`, and every
  `run_sql` response.

## 3. Database

Schema: 5 tables, 8 views. The views exist because two things are easy to get
silently wrong, and an agent should not have to rediscover them per query:

- **Berlin local time.** `ts` is UTC; "July 2025" is a Berlin calendar month.
  Every view exposes `ts_berlin`.
  *A generated column will not work here:* `timestamptz AT TIME ZONE 'literal'`
  is `STABLE`, not `IMMUTABLE`, so Postgres rejects it in `GENERATED ALWAYS AS`.
  Hence views.
- **Renewable share.** The denominator excludes pumped storage, matching how
  SMARD and Fraunhofer ISE report it.

**Read-only role, verified rather than assumed:**

```
SELECT as netzanalyst_ro   -> 12 rows          ✅
INSERT as netzanalyst_ro   -> ERROR: cannot execute INSERT in a read-only transaction  ✅
CREATE TABLE as ..._ro     -> ERROR: cannot execute CREATE TABLE in a read-only transaction  ✅
```

## 4. Failures during the build, and what fixed them

### 4.1 Every HTTPS call failed — `CERTIFICATE_VERIFY_FAILED`

- **Symptom:** the loader could not reach SMARD, but `curl` to the same URL worked.
- **Diagnosis:** the difference between the two ruled out the network. macOS
  python.org builds ship without a usable CA store —
  `ssl.get_default_verify_paths()` pointed at a `cert.pem` that does not exist.
  `certifi` *was* installed, just not wired up.
- **Fix:** build the SSL context from `certifi` when it is importable, falling
  back to the system default. Verification is never disabled.
- **Why this way:** the documented macOS fix is to run
  `Install Certificates.command`, but that patches *your machine* and leaves the
  repo broken for anyone else. Fixing it in the code fixes it everywhere.

### 4.2 `permission denied for table generation`

- **Symptom:** the first real ingest run died instantly; 0 rows written.
- **Diagnosis:** I had applied the schema with `psql` as my own superuser
  account, so the tables were owned by `deek`, not by the `netzanalyst` role the
  loader connects as.
- **Fix:** `scripts/setup-local-db.sh` now applies the schema **as the owner**,
  and the whole setup is one reproducible command instead of ad-hoc `psql`.
- **Lesson:** this class of bug does not appear under Docker, because there
  `POSTGRES_USER` owns everything by construction. Setting it up by hand exposed
  an assumption the compose file was hiding.

### 4.3 June's number labelled as May — the worst bug of the session

- **Symptom:** a query for June 2025 returned `"2025-05-31T22:00:00.000Z"`.
- **Diagnosis:** `node-postgres` parses a Postgres `DATE` into a JavaScript
  `Date` at local midnight; `JSON.stringify` then renders it in UTC. In Berlin
  (UTC+2 in summer) that shifts it back a day.
- **Why it mattered:** nothing would have errored. An agent would have read
  "May 31" and confidently reported June's figure as May's. Silent, plausible,
  wrong — exactly the failure mode this project is meant to avoid.
- **Fix:** explicit type parsers for `DATE`, `TIMESTAMP` and `TIMESTAMPTZ` that
  pass Postgres's own text through untouched.
- **Verified:** `2025-06-01`, `2025-07-01`, `2025-08-01`. ✅

### 4.4 Off-by-one in the ingest window

- **Symptom:** a 7-day range returned **169** rows per series; 7 × 24 = 168.
- **Diagnosis:** the upper bound was inclusive, so it swept in the first hour of
  the following day.
- **Fix:** half-open interval, `start <= ts < end_exclusive`. Re-ran: **168**. ✅

### 4.5 `nuclear: 0 rows` — not a bug

- **Symptom:** the nuclear series loaded 839 rows while every other series
  loaded 23,832.
- **Investigated** rather than assumed: the nuclear index's last chunk is
  **2024-01-28**, and an April 2023 chunk still carries real values (max
  2,691 MW).
- **Conclusion:** correct. Germany shut down its last three reactors on
  15 April 2023 and SMARD stopped publishing the series in January 2024.
- **Turned into an asset:** "how much nuclear did Germany generate in 2025?" is
  now a planned trick question for the eval set. The right answer is *zero, and
  here is why* — not *no data found*.

### 4.6 `brew install terraform` fails

- **Symptom:** the formula is gone from homebrew-core (BUSL licence change), and
  `hashicorp/tap` wants to build from source via Xcode Command Line Tools.
- **Fix:** downloaded the official `darwin_arm64` binary from
  `releases.hashicorp.com` (v1.16.3) to validate the config. Not installed
  system-wide, so **Terraform is still not on your PATH** — see Next steps.

### 4.7 macOS `._*` files, and the one real problem they caused

`/Volumes/Deeksha` is **ExFAT**, which cannot store macOS extended attributes.
macOS therefore writes a sidecar AppleDouble file (`._name`) next to every real
file. There were **1,539** of them. They are junk, they are gitignored, and
`make clean` removes them — but they regenerate as soon as files are written.

They caused one genuine bug: Postgres's init directory runs everything matching
`*.sql`, which would have included `._001_schema.sql` — binary junk — and
failed the container's first start. `docker-compose.yml` therefore mounts the
two init files **individually** rather than mounting the directory.

## 5. Verifying the data is actually correct

Loading without checking would prove nothing. Two independent checks:

### Against published national figures

| Year | Renewable share (ours) | Total generation (ours) | Published |
|---|---:|---:|---|
| 2024 | 60.0% | 427.2 TWh | Fraunhofer ISE ~431 TWh public net generation ✅ |
| 2025 | 60.2% | 428.0 TWh | consistent ✅ |
| 2026 | 63.0% | 321.6 TWh (9 months, partial) | — |

Solar, July 2025: **9,056 GWh, 27.6% of generation** — the brief's own example
question, now answerable.

### Against a completely independent source

August 2026 monthly totals, our SMARD-derived Postgres vs the Energy-Charts API:

| Source | SMARD (GWh) | Energy-Charts (GWh) | Δ |
|---|---:|---:|---:|
| solar | 10,931.4 | 10,931.4 | **0** |
| wind onshore | 7,540.9 | 7,540.9 | **0** |
| wind offshore | 1,824.1 | 1,824.1 | **0** |
| lignite | 4,607.8 | 4,607.8 | **0** |
| hard coal | 2,210.0 | 2,210.0 | **0** |
| natural gas | 2,902.1 | 2,902.1 | **0** |
| biomass | 2,840.9 | 2,716.4 | **−4.4%** |

Six of seven match **to the decimal**. That simultaneously confirms the unit
handling (MWh), the Berlin month boundaries, and the fidelity of the loader.
Biomass differs by 4.4% — almost certainly a classification difference in how
biogenic waste is split. Documented so it is not later mistaken for a bug.

**Final load: 358,319 rows**, 2024-01-01 → 2026-09-19, 16 series.

## 6. MCP server

> **Deviation from the brief, flagged and approved.** The brief specifies
> `@modelcontextprotocol/sdk`. That package (v1.30.0, last released July 2026)
> is the **pre-split** SDK; the same official repo now publishes
> `@modelcontextprotocol/server` v2, actively released through September 2026.
> Dee chose v2.

> **I guessed the transport API and was wrong.** I wrote the HTTP server against
> a `PerRequestHTTPServerTransport.handleRequest(req, res)` method that does not
> exist. `tsc` caught it. Reading the shipped `.d.ts` showed the real surface:
> `createMcpHandler(factory)` returning a **web-standard** `fetch(Request) ->
> Response`. Rewritten against the actual API, plus a Node↔fetch bridge and
> `hostHeaderValidationResponse` / `originValidationResponse` for
> DNS-rebinding protection. **Read the types, do not recall the API.**

`run_sql` is defended in four independent layers, so no single mistake is enough:

1. a `SELECT`-only role with `default_transaction_read_only = on`
2. an explicit `BEGIN READ ONLY` around every query
3. a SQL guard that blanks comments, string literals and dollar-quoted blocks
   *before* scanning for keywords and semicolons
4. a row cap and statement timeout

**19 unit tests, all passing**, including smuggling attempts:

```
SELECT 1 -- harmless\n; DROP TABLE generation     -> rejected
SELECT 1 /* a /* b */ still */ ; DROP TABLE price -> rejected (nested comments)
SELECT $$x$$ ; DROP TABLE price                   -> rejected (dollar quoting)
SELECT 'a;b' AS s                                 -> allowed (semicolon in a string)
SELECT created_at FROM ingest_log                 -> allowed ("create" inside an identifier)
```

**Verified over the real MCP wire protocol**, not just by unit test —
`initialize` → `tools/list` → `tools/call` against the running server:

```
initialize          -> protocolVersion 2025-06-18, serverInfo netzanalyst 0.1.0   ✅
tools/list          -> get_schema, run_sql, fetch_energy_charts                   ✅
run_sql (valid)     -> rows, with attribution                                     ✅
run_sql "DROP ..."  -> "Only read queries are allowed ... starts with \"drop\""   ✅
fetch_energy_charts -> 48 hourly points, licence string passed through            ✅
fetch_energy_charts (243-day range) -> rejected with a message naming the limit   ✅
```

## 7. Terraform

Written, formatted, `init -backend=false` and **`terraform validate` → Success**.
**Nothing has been applied. No Azure resource exists. Nothing is billing.**

One deprecation was surfaced by `validate` and fixed:
`enable_rbac_authorization` → `rbac_authorization_enabled`.

`infra/terraform/foundry.tf` is **deliberately empty**. The brief's own rule is
to check current docs before writing against Foundry preview features. Writing
`azapi` resources against a remembered preview API version is how you get a plan
that fails at apply — or worse, one that succeeds and bills.

## 8. Repo structure and tooling (added after Dee's feedback)

Restructured from the brief's layout to a conventional one:

- **`src/netzanalyst/`** — one installable package, so ingest, agents and evals
  can share configuration and database code instead of duplicating it. Moved
  with `git mv`, so history is preserved.
- **`services/`** — deployable services (`mcp-server`, later `a2a-client`).
- **`db/migrations/`** — numbered SQL migrations.
- **`tests/`** — pytest, separate from the package.
- **`pyproject.toml`** — one place for dependencies, lint, types and test config,
  replacing a loose `requirements.txt` and `ruff.toml`.
- **`Makefile`** — one entry point: `make setup`, `make db-up`, `make check`.

On tooling: **Ruff replaces Pylint, Black and isort** rather than running
alongside them — it is the same checks in one fast tool, and three formatters on
the same files only fight. What was actually missing was type checking and
secret scanning, so added:

- **mypy `--strict`** — found 8 real gaps, all fixed, now clean.
- **Pydantic + pydantic-settings** — for settings validation and, next, the
  structured hand-offs between agents.
- **pre-commit** with gitleaks and `detect-private-key` — the brief's hard rule
  is that no secret reaches the repo, and a linter cannot enforce that.
- **pytest-cov** — currently 29%, honestly reported; most of the uncovered code
  is network and database I/O.

CI now has five jobs: `mcp-server`, `python`, `secrets`, `sql`, `terraform`.

## 9. The `._*` files — root cause and the only real fix

`/Volumes/Deeksha` is **ExFAT**, which cannot store macOS extended attributes
inline. macOS stamps `com.apple.provenance` on files it creates, so that
attribute spills into a sidecar `._name` file. Verified directly:

```
$ xattr -l src            -> com.apple.provenance
$ diskutil info /Volumes/Deeksha | grep Personality  -> ExFAT
$ diskutil info / | grep Personality                 -> APFS   (internal disk)
```

**The common advice does not work here:**

| Suggested fix | Why it does not apply |
|---|---|
| `COPYFILE_DISABLE=1` | Only affects `tar`/`cp`, not ordinary file writes |
| `defaults write ... DSDontWriteNetworkStores` | Only affects `.DS_Store` on network shares |
| `dot_clean` | Removes them, but they reappear on the next write |

There is **no setting that disables this on ExFAT.** The only real fix is to
keep the repo on an APFS volume — the internal disk, which had 54 GB free
against a 862 MB repo.

**Dee's decision: stay on `/Volumes/Deeksha`.** The sidecars are gitignored and
never reach a commit, and each of the three problems below now has a permanent
guard in the code rather than a manual workaround. `make clean` removes the
Terraform provider cache before running `dot_clean`, precisely so problem 3
cannot recur.

They are gitignored and never reach a commit, but they are not merely cosmetic.
They caused **three real problems** in one session:

1. Postgres's init directory runs everything matching `*.sql`, which would have
   included the binary `._001_schema.sql` and failed the container's first
   start. `docker-compose.yml` now mounts the two init files individually.
2. The prompt loader globbed `*.yaml`, picked up `._sql_agent.yaml`, and died on
   a `UnicodeDecodeError`. The loader now skips `._*` — worth having anyway,
   since the same thing happens to anyone installing from a macOS-built archive.
3. `dot_clean` stripped attributes from the extracted Terraform provider
   binaries, breaking their recorded checksums and making `terraform validate`
   fail with "missing or corrupted provider plugins". Fixed by deleting
   `.terraform/` and re-initialising.

## 10. Repo structure, tooling and prompts (Dee's feedback)

### Structure

Moved from the brief's layout to a conventional one, with `git mv` so history
survives (git recorded every move as `R100`, a 100% similarity rename):

| Before | After | Why |
|---|---|---|
| `data/ingest/` | `src/netzanalyst/ingest/` | Python code belongs in one installable package, not in a directory named after data |
| `mcp-server/` | `services/mcp-server/` | Groups deployable services; `a2a-client` joins it later |
| `sql/` | `db/migrations/` | Numbered migrations, conventional name |
| `data/README.md` | `docs/data-sources.md` | It is documentation |
| `requirements.txt`, `ruff.toml` | `pyproject.toml` | One place for dependencies, lint, types and tests |
| — | `tests/`, `Makefile` | A test suite, and one entry point for every task |

The point of the package is shared code: `config.py` and the database access
are written once and imported by ingest, agents and evals, rather than each
re-reading `os.environ` in its own way.

### Tooling: what was added, and what was deliberately refused

**Refused: Pylint, Black, isort.** Ruff already does all three — it is a
Black-compatible formatter, an import sorter, and covers most Pylint rules, in
one fast tool. Running them alongside Ruff means three tools reformatting the
same files and disagreeing.

**Added, because they were genuinely missing:**

| Tool | What it caught |
|---|---|
| **mypy `--strict`** (+ Pydantic plugin) | 8 real gaps: untyped JSON payloads, an untyped `conn` parameter, missing return annotations. Clean now. |
| **Pydantic / pydantic-settings** | Typed settings that fail at startup rather than mid-run. A validator rejects a "read-only" URL that does not use a `*_ro` role — that would silently remove a security layer. |
| **gitleaks + detect-private-key** | The brief's hard rule is that no secret reaches the repo; a linter cannot enforce that. |
| **pytest-cov** | 49% and honestly reported. Most of the gap is network and database I/O. |

> **A mypy lesson worth keeping.** mypy first reported "missing named argument"
> for every Pydantic model construction. The wrong fix is to sprinkle
> `# type: ignore`. The right one is `plugins = ["pydantic.mypy"]`, which
> teaches mypy that fields with defaults are optional. Two ignores were added
> and then removed once the plugin was enabled.

### Prompts as YAML

Agent prompts now live in `src/netzanalyst/prompts/*.yaml`, validated against a
Pydantic `PromptSpec` on load, rather than inside Python string literals:

- **Reviewable** — a prompt change is a readable diff.
- **Versioned** — each carries a `version`, and `identifier()` returns
  `sql_agent@v3`. That goes into the eval results, so "accuracy rose from 82% to
  91%" is attributable to a specific revision. This is what makes the brief's
  before/after comparison meaningful.
- **Swappable** — comparing two prompts means pointing the loader at a different
  file, not editing code.

Four prompts written, each encoding the caveats discovered earlier in the
session, so the agents inherit them rather than rediscovering them:

```
orchestrator@v1     default  2000 tokens  no tools
sql_agent@v1        default  1500 tokens  get_schema, run_sql, fetch_energy_charts
analysis_agent@v1   analysis 3000 tokens  no tools
verifier_agent@v1   default  1200 tokens  get_schema, run_sql
```

The tests enforce properties, not just loading: prompts may only reference tools
the MCP server actually registers; every agent must cap its output tokens (the
brief's cost rule); and only `analysis_agent` may claim the expensive model.

**26 Python tests + 19 MCP server tests, all passing.**

# Session 2 — 2026-09-20 (continued): Week 2 begins

## 11. Published to GitHub

Repo: <https://github.com/deekshavishnoi/netzanalyst>, public.

Two things broke on the first push, both worth knowing:

1. **SSH push rejected** — `gh` was configured for SSH but no key was
   registered. Switched the remote to HTTPS with `gh auth setup-git`.
2. **`refusing to allow an OAuth App to ... workflow without 'workflow' scope`**
   — the `gh` token could not create `.github/workflows/ci.yml`. Fixed with
   `gh auth refresh -h github.com -s workflow`, which needs a browser and so
   had to be Dee's step.

### CI failed on its first run, for a reason worth recording

Four of five jobs passed. **The secret scan failed — and failed dishonestly.**

`gitleaks-action` scans the commit range `<before>^..<after>`. On a repository's
*first* push the initial commit has no parent, so:

```
fatal: ambiguous argument '49006d3^..9dd8703': unknown revision
WRN scanned ~0 bytes (0)
WRN no leaks found in partial scan
```

It scanned **zero bytes**, reported "no leaks found", and still failed the job —
the worst combination: a red build that would have gone green while checking
nothing.

Replaced with the pinned gitleaks binary run directly, scanning full history and
the working tree as separate steps. Verified locally first (6 commits, no leaks,
exit 0) rather than iterating through CI. **All five jobs now pass.**

## 12. Azure and Foundry: two findings that change the brief

Researched against Microsoft Learn before writing any Foundry code, per the
brief's own rule. Both findings are blocking, and neither was foreseeable from
the brief.

### Finding 1 — a free trial cannot deploy any LLM

The **$200 credit and the model quota are separate controls.** Free Trial,
Lightweight Trial and **Azure Pass** subscriptions start with **0 tokens-per-minute
for every GPT model in every region**, by design, to prevent abuse.

Dee's subscription came from the AI-102/103 certification course, which is
typically an Azure Pass — and she had already hit exactly this: `gpt-4.1-mini`
would not deploy in Germany West Central.

**The region was not the cause.** Microsoft's own table lists `gpt-4.1-mini` as
available in `germanywestcentral`, so moving to Sweden Central would not have
fixed it. Diagnostic added to `docs/azure-setup.md`:

```
az cognitiveservices usage list --location germanywestcentral --output table
```

A limit of 0 confirms quota, not region. The only fix is upgrading to
Pay-As-You-Go, which **keeps** the remaining credit.

### Finding 2 — `gpt-5.4-mini` is not agent-supported

The brief specifies `gpt-5.4-mini` everywhere. It **is** deployable as Global
Standard Azure OpenAI, but it is **not on the agent-supported list** for Foundry
Agent Service, which only runs models onboarded for agent workflows. The entire
design runs agents on Agent Service.

Default is now **`gpt-4.1-mini`** — agent-supported, cheapest, widest regions.
`variables.tf` records the whole ladder, which doubles as the model comparison
the brief asks for in section 8:

```
gpt-4.1-mini  agent-supported, cheapest, widest regions   <- default
gpt-5-mini    agent-supported, stronger reasoning
gpt-5         agent-supported, most capable
gpt-5.4-mini  NOT agent-supported
```

### What the same research confirmed as sound

- **Hosted agents are GA** and explicitly support Microsoft Agent Framework.
- **Custom remote MCP servers are supported**, authenticated by the agent's
  managed identity — our MCP server plugs in as designed.
- **A2A v1.0 is generally available**, with a documented endpoint how-to. The
  optional last layer is real, not preview guesswork.

## 13. The agents

> **`pip install agent-framework` did not finish in 25 minutes.** It is a
> meta-package pulling in every optional provider, and the resolver backtracks
> endlessly. Killed it and installed `agent-framework-core` instead: **seconds.**
> Worth knowing before you sit watching a progress bar.
>
> Also worth knowing: **`agent-framework-core` is 1.19.0 (GA) but
> `agent-framework-azure-ai` is 1.0.0rc6** — the Azure binding is still a
> release candidate while the core is stable. It is isolated in its own extra.

Introspected the API rather than recalling it — the lesson from the MCP
transport mistake — and found Agent Framework ships **native MCP support**:

```
MCPStreamableHTTPTool(name, url, *, allowed_tools=..., request_timeout=...)
Agent(client=..., instructions=..., name=..., tools=[...])
```

So the MCP server connects with **no custom client code at all**, and
`allowed_tools` maps straight onto the `tools:` list each prompt already
declares. Tool access becomes least-privilege *by construction* rather than by
asking the model nicely:

| Agent | Model tier | MCP tools |
|---|---|---|
| orchestrator | default | none — delegates only |
| sql_agent | default | `get_schema`, `run_sql`, `fetch_energy_charts` |
| analysis_agent | **analysis** | none — computes from rows it is handed |
| verifier_agent | default | `get_schema`, `run_sql` (**not** the live API) |

The verifier deliberately cannot reach Energy-Charts: it must check against the
same data the answer came from, not a second source that might disagree for
unrelated reasons (see the 4.4% biomass difference in `docs/data-sources.md`).

One `OpenAIChatClient` covers every provider — `azure_endpoint` for Foundry with
`DefaultAzureCredential` so no key ever enters the process, `api_key` for
OpenAI, `base_url` for Ollama. That is the brief's portability requirement met
in one class.

### Two bugs the tooling caught before they could bite

- `Settings.azure_openai_api_version` was referenced in the factory but never
  defined. **mypy caught it**, not a runtime failure on the first Azure call.
- `Agent` has no `.instructions` attribute; the system prompt lives in
  `default_options["instructions"]`. **The tests caught it.** I had guessed the
  attribute rather than checking.

**51 Python tests + 19 MCP server tests passing. Coverage 63%.**

### Not yet done: the agents have never answered a real question

They build, they are wired correctly, and the wiring is tested — but **no model
has been called.** There is no provider available locally: Ollama is not
installed, no OpenAI or Anthropic key is set, and Azure is blocked on the quota
upgrade. Until one exists, "the agents work" is an unproven claim and is not
recorded as done anywhere.

## 14. The evaluation question set

Built without a model, since none is available yet — and it is the piece that
makes everything afterwards measurable.

**33 questions**: 12 lookups, 6 comparisons, 7 trends, 8 traps. Within the
brief's 30–50, and the mix it asks for.

**No answer is hand-written.** Each question carries the SQL that produced it,
and `python -m netzanalyst.evals.generate` runs that SQL against the database.
A question set whose answers cannot be recomputed rots silently the first time
the data is reloaded; this one regenerates.

Spot-check of the grounded values, against what these figures should be:

| Question | Answer | Plausible? |
|---|---:|---|
| Solar share, July 2025 | 27.60% | ✅ the brief's own example |
| Total generation, 2025 | 428.0 TWh | ✅ |
| Renewable share, 2025 | 60.2% | ✅ |
| Peak load, 2025 | 75,635 MW | ✅ |
| Average price, 2025 | €89.32/MWh | ✅ |
| Negative-price hours, 2025 | 573 | ✅ 6.5% of the year |
| Peak solar hour, 2025 | 52,132 MW | ✅ |

### Two problems found while grounding the answers

Both would have produced a question set that quietly graded the wrong thing.

**`zero-solar-hours-2025` returned 0, and that was correct.** Solar in this data
is *never exactly zero*: the 2025 minimum is 4 MW and a typical summer night
sits near 60 MW.

```
exactly_zero | nulls | tiny_positive | min_val | total
           0 |     0 |          2124 |       4 |  8760

2025-06-15 02:00 -> 53.0 MW      <- the middle of a June night
```

So "how many hours was solar zero?" had the answer 0 for a reason no model would
guess, and any sensible answer ("about half the year, at night") would be marked
wrong. Replaced with **`min-solar-hour-2025`**, which catches the same wrong
assumption — reasoning "the sun is down, so zero" instead of reading the data —
but has an answer that can actually be defended.

**A near-zero expected value cannot use a relative tolerance.** The
2024→2025 renewable share change is **0.27 percentage points**. At ±5% relative
that demands ±0.013 — effectively exact, so the question was unpassable. Added
`tolerance_abs` to the schema, set to 0.5 points here.

### Scoring distinguishes a refusal from a zero

These are different failures and are scored separately:

- **Answering `0` to an unanswerable question is wrong** (solar in 2030).
- **Refusing a genuine zero is also wrong** (nuclear in 2025 is zero *because
  the reactors are gone*, not unanswerable).

Every trap additionally requires explanatory phrases, because the point of a
trap is the reasoning, not the number. Nuclear is asked for two different
periods so the explanation cannot be memorised for one date.

The tests treat the question set as a build artefact in its own right: unique
ids, all four categories present, every numeric answer reproducible from its
SQL, every trap carrying a note and required phrases, and near-zero answers
using an absolute tolerance.

**62 Python tests + 19 MCP server tests passing.**

## Where things stand

| Layer | State |
|---|---|
| Data ingest | ✅ 358,319 rows, cross-validated |
| Database + views | ✅ schema, read-only role verified |
| MCP server | ✅ 3 tools, verified over the wire, 19 tests |
| Settings + prompts | ✅ typed, validated, 26 tests |
| Tooling + CI | ✅ 5 jobs, **all passing on GitHub** |
| GitHub | ✅ public at deekshavishnoi/netzanalyst |
| Terraform | ✅ validates, lock committed, **nothing applied** |
| Agents | 🟡 all four build and are wired, but **have never called a model** |
| Agent contracts | ✅ typed hand-offs, accuracy rules enforced in the models |
| Evals | 🟡 33 questions grounded and committed; **runner not written** |
| A2A | ⬜ optional, last |

## Next steps

**Blocked on a model provider.** Dee chose to wait for Azure rather than install
Ollama, so the agents cannot be run until the subscription is upgraded and
`gpt-4.1-mini` is deployed. Until then:

1. Write the eval runner and scorer — it can be tested against recorded
   responses without calling a model.
2. Write the orchestration workflow wiring with `WorkflowBuilder`.
3. Point an MCP client at the server and take the **"MCP server tools listed in
   an MCP client"** screenshot for the documentation checklist.
4. Install Terraform properly (it is only in a temp directory) and Docker, then
   test the `docker compose up` path.

Once Azure is unblocked: deploy the model, run the agents end to end, write
`foundry.tf`, and take the first real evaluation baseline.

## Open items for Dee

- **Trial dates are still blank in the brief.** Everything must land before the
  earlier of the trial end and 23 Oct.
- **Day-one Azure checks, blocking for Week 2:** confirm `gpt-5.4-mini` can be
  deployed and a hosted agent created on the trial; set budget alerts at
  $50 / $100 / $150.
- **Model names are unverified.** `gpt-5.4-mini` and `gpt-5.4` come from the
  brief and have not been checked against what the trial can deploy. They are
  currently only defaults in `variables.tf`. If they are unavailable, say so and
  we re-plan the model choice.
