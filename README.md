# netzanalyst

Ask questions about German electricity in plain English; get a correct answer,
a chart, and the numbers checked before they reach you.

> **How much of Germany's electricity came from solar in July 2025?**

netzanalyst pulls the real figures from a database of SMARD data, computes the
answer, draws a chart, re-checks its own arithmetic against the raw numbers, and
replies.

**Status: in development.** The data layer and MCP server work end to end
locally. Agents, evaluation and Azure deployment are next. See
[docs/progress.md](docs/progress.md).

---

## What it demonstrates

- A custom **MCP server** in TypeScript exposing read-only energy data
- **Multi-agent orchestration** with Microsoft Agent Framework
- An **A2A endpoint**, so other agents can call netzanalyst
- **Terraform** for all Azure infrastructure
- **Evaluation** with measured accuracy and cost on a 30–50 question set

## Architecture

```
User question
    │
    ▼
Orchestrator agent ── plans the steps, hands off work
    │
    ├── SQL agent ────────► MCP server ──► PostgreSQL (SMARD history)
    │                           └────────► Energy-Charts API (fresh data)
    ├── Analysis agent ── runs Python, makes charts (Code Interpreter)
    └── Verifier agent ── re-checks numbers before the answer goes out
    │
    ▼
Answer + chart

External agents ──A2A──► netzanalyst orchestrator
```

## MCP server

Three read-only tools, served over streamable HTTP at `/mcp` or over stdio.

| Tool | What it does |
|---|---|
| `get_schema` | Tables, columns, comments, actual data coverage, and the usage notes an agent needs to write correct SQL |
| `run_sql` | One guarded read-only `SELECT`, row-capped and timed out |
| `fetch_energy_charts` | Recent generation from Fraunhofer ISE, for dates newer than the database |

### How `run_sql` is kept safe

Four independent layers, so no single mistake is enough:

1. **A dedicated role.** `netzanalyst_ro` has `SELECT` only, with
   `default_transaction_read_only = on` and a server-side `statement_timeout`.
   The server is never given the owner role.
2. **An explicit `BEGIN READ ONLY` transaction** around every query.
3. **A SQL guard** that rejects anything but a single leading `SELECT`/`WITH`.
   It blanks out comments, string literals and dollar-quoted blocks *before*
   scanning, so a write cannot be smuggled past it inside a quote or a comment.
   Covered by 19 unit tests.
4. **A row cap and statement timeout** on every call.

Rejections are phrased so a model can correct itself:

```
Query rejected: Only a single statement is allowed. Remove the ';' and send one SELECT.
Query rejected: LIMIT 500000 exceeds the maximum of 1000 rows. Aggregate in SQL instead.
```

## Run it locally

Everything below runs without Azure and without any cloud credentials.

### 1. Database

**With Docker** (the portable path):

```bash
cp .env.example .env    # then edit the two passwords
docker compose up -d
```

**Or with a native Postgres** (e.g. `brew install postgresql@16`):

```bash
cp .env.example .env    # then edit the two passwords
export PATH="/opt/homebrew/opt/postgresql@16/bin:$PATH"
./scripts/setup-local-db.sh
```

Either way you get the schema, the seeded source dimension, and a read-only role
whose write access is verified to fail.

### 2. Load the data

```bash
pip install -r data/ingest/requirements.txt
set -a; . ./.env; set +a
python data/ingest/smard.py --from 2024-01-01 --to $(date +%F)
```

Roughly 400k rows and about 13 minutes. The loader is idempotent, so
interrupting and re-running it is safe. Add `--dry-run` to fetch and validate
without writing.

### 3. MCP server

```bash
cd mcp-server
npm install
npm run build
npm start          # HTTP on :3000, MCP at /mcp, health at /health
npm run stdio      # or stdio, for Claude Desktop / MCP Inspector
```

Check it:

```bash
curl -s localhost:3000/health
```

To use it from an MCP client over stdio, point the client at
`node /absolute/path/to/mcp-server/dist/index.js --stdio` with
`DATABASE_URL_READONLY` set in its environment.

## Repo layout

```
data/ingest/     SMARD downloader and loader
sql/             schema, views, read-only role
mcp-server/      TypeScript MCP server
agents/          Python, Microsoft Agent Framework        (next)
evals/           question set, runner, committed results  (next)
a2a-client/      agent that calls netzanalyst over A2A    (optional)
infra/terraform/ Azure infrastructure                     (next)
docs/            progress log, architecture, cost
```

## Data

Two public sources, both English, both CC BY 4.0. Full detail, including the
caveats the agents have to respect, is in [data/README.md](data/README.md).

- **SMARD** (Bundesnetzagentur) — bulk hourly history, loaded into Postgres.
  Fetched from the JSON endpoints behind smard.de's charts, which are
  **not an official documented API**; the loader validates every response and
  fails loudly rather than writing bad numbers.
- **Energy-Charts** (Fraunhofer ISE) — recent data, queried live via a
  documented OpenAPI service.

Four caveats that would otherwise produce confident wrong answers, and are
encoded in the schema comments and the eval set:

- Nuclear generation **ends January 2024** — Germany's last reactors shut down
  in April 2023. "How much nuclear in 2025?" is *zero by policy*, not *no data*.
- Pumped storage is **not** renewable and is excluded from share denominators.
- Day-ahead prices **can be negative**. That is real, not an error.
- Timestamps are UTC; German questions mean Berlin local time, and Berlin has DST.

> Electricity data: **Bundesnetzagentur | SMARD.de** and **Energy-Charts,
> Fraunhofer ISE**, both licensed under
> [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).

## Results

Filled in once the evaluation runs. Planned metrics: answer accuracy within
±1%, SQL success rate, wrong answers caught by the verifier, average latency,
and average cost per question from trace token counts.

## Licence

Code: MIT. Data: CC BY 4.0, attributed above.
