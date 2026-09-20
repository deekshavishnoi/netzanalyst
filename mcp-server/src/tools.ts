/** The three MCP tools netzanalyst exposes. All read-only. */

import * as z from "zod";
import type { McpServer } from "@modelcontextprotocol/server";
import { config } from "./config.js";
import { describeSchema, runReadOnly } from "./db.js";
import { fetchEnergyCharts, EnergyChartsError } from "./energy-charts.js";
import { guardSelect, SqlGuardError } from "./sql-guard.js";

const ATTRIBUTION =
  "Data: Bundesnetzagentur | SMARD.de, CC BY 4.0. " +
  "Recent data: Energy-Charts, Fraunhofer ISE, CC BY 4.0.";

/** Guidance the SQL agent needs and cannot infer from column names alone. */
const SCHEMA_NOTES = `
Notes for writing correct queries

- Timestamps (ts) are timestamptz stored in UTC. German questions almost always
  mean Berlin local time, so prefer the v_* views: each exposes ts_berlin.
  Europe/Berlin observes DST, so some days have 23 or 25 hours.
- Units: generation and consumption are MWh per hour (numerically the same as
  average MW at hourly resolution). Prices are EUR/MWh and CAN BE NEGATIVE.
- Renewable share: use v_renewable_share_monthly or v_generation_share_monthly.
  Both exclude category='storage' (pumped storage) from the denominator, which
  is how SMARD and Fraunhofer ISE report the figure. Do not reinvent this.
- Nuclear: Germany shut down its last reactors on 15 April 2023 and the SMARD
  nuclear series ends in January 2024. For any later period the answer is zero
  by policy, not "missing data". Say so explicitly.
- mwh can be NULL for recent, not-yet-published hours. SUM() skips NULLs, so
  check counts with v_data_coverage before reporting a total as complete.
- Always check v_data_coverage when a question names a period, so you do not
  report a partial month as if it were complete.
`.trim();

function textResult(text: string, isError = false) {
  return { content: [{ type: "text" as const, text }], isError };
}

export function registerTools(server: McpServer): void {
  // -------------------------------------------------------------------------
  server.registerTool(
    "get_schema",
    {
      title: "Get database schema",
      description:
        "Return the tables, views, columns and usage notes for the German " +
        "electricity database. Call this before writing SQL with run_sql.",
      inputSchema: z.object({}),
    },
    async () => {
      try {
        const schema = await describeSchema();
        const coverage = await runReadOnly(
          "SELECT table_name, first_ts, last_ts, row_count FROM v_data_coverage ORDER BY table_name",
        );
        const coverageText = coverage.rows
          .map(
            (r) =>
              `  ${String(r["table_name"]).padEnd(12)} ${String(r["first_ts"] ?? "-")} .. ${String(r["last_ts"] ?? "-")}  (${String(r["row_count"])} rows)`,
          )
          .join("\n");
        return textResult(
          `${schema}\n\nDATA COVERAGE\n${coverageText}\n\n${SCHEMA_NOTES}\n\n${ATTRIBUTION}`,
        );
      } catch (error) {
        return textResult(`Could not read the schema: ${(error as Error).message}`, true);
      }
    },
  );

  // -------------------------------------------------------------------------
  server.registerTool(
    "run_sql",
    {
      title: "Run a read-only SQL query",
      description:
        `Run a single read-only SELECT against the German electricity database and ` +
        `return the rows as JSON. Only SELECT and WITH are permitted; at most ` +
        `${config.maxRows} rows are returned. Aggregate in SQL rather than ` +
        `returning raw hourly rows. Call get_schema first.`,
      inputSchema: z.object({
        sql: z
          .string()
          .min(1)
          .describe("A single SELECT or WITH statement. No semicolon needed."),
      }),
    },
    async ({ sql }) => {
      let guarded;
      try {
        guarded = guardSelect(sql, config.maxRows);
      } catch (error) {
        if (error instanceof SqlGuardError) {
          return textResult(`Query rejected: ${error.message}`, true);
        }
        throw error;
      }

      try {
        const result = await runReadOnly(guarded.sql);
        const truncated = result.rowCount >= guarded.limit;
        const payload = {
          row_count: result.rowCount,
          elapsed_ms: result.elapsedMs,
          truncated,
          limit_applied: guarded.limitApplied ? guarded.limit : null,
          columns: result.fields.map((f) => f.name),
          rows: result.rows,
          attribution: ATTRIBUTION,
          ...(truncated
            ? {
                warning:
                  `Exactly ${guarded.limit} rows came back, so the result is probably cut off. ` +
                  `Aggregate in SQL (GROUP BY, SUM, AVG) instead of returning raw rows.`,
              }
            : {}),
        };
        return textResult(JSON.stringify(payload, null, 2));
      } catch (error) {
        const message = (error as Error).message;
        // Postgres errors are genuinely useful to an LLM: they name the missing
        // column or the syntax problem, so pass them through rather than hiding
        // them behind a generic failure.
        return textResult(
          `The query failed: ${message}\n\nCall get_schema to check table and column names.`,
          true,
        );
      }
    },
  );

  // -------------------------------------------------------------------------
  server.registerTool(
    "fetch_energy_charts",
    {
      title: "Fetch recent data from Energy-Charts",
      description:
        "Fetch recent German electricity generation from the Energy-Charts API " +
        "(Fraunhofer ISE) for a date range of at most 31 days. Use this only for " +
        "periods newer than the database coverage shown by get_schema; for " +
        "anything the database already holds, use run_sql, which is faster.",
      inputSchema: z.object({
        start: z.string().describe("Inclusive start date, YYYY-MM-DD."),
        end: z.string().describe("Inclusive end date, YYYY-MM-DD. At most 31 days after start."),
        country: z
          .string()
          .default("de")
          .describe("Two-letter country code. Defaults to 'de' (Germany)."),
      }),
    },
    async ({ start, end, country }) => {
      try {
        const result = await fetchEnergyCharts(start, end, country ?? "de");
        return textResult(JSON.stringify(result, null, 2));
      } catch (error) {
        if (error instanceof EnergyChartsError) {
          return textResult(`Energy-Charts request failed: ${error.message}`, true);
        }
        throw error;
      }
    },
  );
}
