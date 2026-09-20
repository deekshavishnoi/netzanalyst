# Data sources and terms of use

netzanalyst uses two public sources, both covering German electricity and both
offering English interfaces.

## 1. SMARD — Bundesnetzagentur (bulk history, loaded into Postgres)

- Site: <https://www.smard.de/en>
- Download centre: <https://www.smard.de/en/downloadcenter/download-market-data>
- **Licence: CC BY 4.0.** SMARD states that its data "can be downloaded, stored
  and used free of charge". Attribution is required.
- **Required attribution:** *Data: Bundesnetzagentur | SMARD.de, licensed under
  CC BY 4.0.*

### How we fetch it

The ingest script calls the JSON endpoints that smard.de itself uses to render
its charts:

```
index  /app/chart_data/{filter}/{region}/index_{resolution}.json
data   /app/chart_data/{filter}/{region}/{filter}_{region}_{resolution}_{ts}.json
```

> **These endpoints are not an official, documented API.** They are catalogued
> by [bundesAPI/smard-api](https://github.com/bundesAPI/smard-api) but the
> Bundesnetzagentur does not publish them as a public API contract, so they can
> change without notice.
>
> Mitigations in `ingest/smard.py`: every response is shape-checked, every value
> is range-checked against a plausibility band before it is written, and the
> loader is idempotent so a re-run after a breakage is always safe. If SMARD
> changes the format the ingest fails loudly instead of writing bad numbers.
>
> The manual CSV download centre is the documented fallback if the endpoints go
> away.

We request at roughly 5 requests/second with a descriptive User-Agent. There is
no published rate limit; be conservative.

### Filter IDs in use

| ID | Series | Table |
|---|---|---|
| 1223 | Lignite (brown coal) | `generation` |
| 1224 | Nuclear | `generation` |
| 1225 | Wind offshore | `generation` |
| 1226 | Hydropower | `generation` |
| 1227 | Other conventional | `generation` |
| 1228 | Other renewable | `generation` |
| 4066 | Biomass | `generation` |
| 4067 | Wind onshore | `generation` |
| 4068 | Solar (photovoltaic) | `generation` |
| 4069 | Hard coal | `generation` |
| 4070 | Pumped storage (generating) | `generation` |
| 4071 | Natural gas | `generation` |
| 410  | Total load (Netzlast) | `consumption` |
| 4359 | Residual load | `consumption` |
| 4387 | Pumped storage (consuming) | `consumption` |
| 4169 | Day-ahead price, DE-LU | `price` |

## 2. Energy-Charts — Fraunhofer ISE (fresh/recent data, queried live)

- API: <https://api.energy-charts.info/> (OpenAPI 2.0 spec at `/openapi.json`)
- Publishing notes: <https://energy-charts.info/publishing-notes.html>
- **Licence: CC BY 4.0**, stated in every API response body under `license`:
  `"CC BY 4.0 (creativecommons.org/licenses/by/4.0), attribution: energy-charts.info"`
- **Required attribution:** *Data: Energy-Charts, Fraunhofer ISE, licensed under
  CC BY 4.0.*

Used by the MCP tool `fetch_energy_charts` for recent data that is not in the
database yet. Main endpoint: `GET /v2/public_power?country=de&start=&end=`,
which returns 15-minute resolution values in MW.

## Data caveats the agents must respect

These are real properties of the data. Getting them wrong produces confident
wrong answers, so they are encoded in the schema comments, surfaced by the
`get_schema` MCP tool, and covered by the eval set.

1. **Nuclear generation ends 2024-01-28.** Germany shut down its last three
   reactors on 15 April 2023, and SMARD's nuclear series stops publishing in
   January 2024. A question like "how much nuclear power did Germany generate in
   2025?" has the answer *zero / not applicable*, not *no data found*. The
   system should say why.
2. **Pumped storage is not renewable.** It appears in `generation` with
   `category = 'storage'` and is excluded from the renewable-share views, which
   matches how SMARD and Fraunhofer ISE report the figure.
3. **Prices can be negative.** Negative day-ahead prices are normal in hours of
   high wind and solar. Do not clamp or treat them as errors.
4. **Timestamps are UTC; German questions mean Berlin local time.** Every view
   exposes `ts_berlin`. Europe/Berlin observes DST, so a "day" is sometimes 23
   or 25 hours.
5. **Values may be NULL.** Recent hours are often provisional or not yet
   published. Aggregates must not silently treat NULL as zero.
6. **Units.** Generation and consumption are MWh per hour (numerically equal to
   average MW at hourly resolution). Prices are EUR/MWh.

## Cross-validation between the two sources

August 2026 monthly totals, SMARD (our Postgres) vs Energy-Charts, in GWh:

| Source | SMARD | Energy-Charts | Difference |
|---|---:|---:|---:|
| solar | 10,931.4 | 10,931.4 | 0 |
| wind onshore | 7,540.9 | 7,540.9 | 0 |
| wind offshore | 1,824.1 | 1,824.1 | 0 |
| lignite | 4,607.8 | 4,607.8 | 0 |
| hard coal | 2,210.0 | 2,210.0 | 0 |
| natural gas | 2,902.1 | 2,902.1 | 0 |
| **biomass** | **2,840.9** | **2,716.4** | **-4.4%** |

Six of seven match exactly, which confirms the ingest's unit handling (MWh) and
the Berlin-month boundaries in the views are correct. The two services
ultimately republish the same ENTSO-E transparency data.

**Biomass is the exception** and differs by about 4.4%, almost certainly a
classification difference (how biogenic waste is split between "biomass" and
"other renewable"). Do not treat a biomass mismatch between the two tools as a
bug, and prefer one source consistently within a single answer rather than
mixing them.

## Attribution block for the README

> Electricity data: **Bundesnetzagentur | SMARD.de** and **Energy-Charts,
> Fraunhofer ISE**, both licensed under
> [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/).
