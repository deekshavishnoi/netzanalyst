/** Postgres access for the MCP tools. Read-only, bounded, and timed out. */

import pg from "pg";
import { config } from "./config.js";

// Return numerics and int8 as JavaScript numbers rather than strings. Node's
// double has 53 bits of integer precision, far more than any MWh figure here,
// and agents reason much better about 12345.6 than "12345.6".
pg.types.setTypeParser(pg.types.builtins.NUMERIC, Number.parseFloat);
pg.types.setTypeParser(pg.types.builtins.INT8, (v) => Number.parseInt(v, 10));

// Hand dates and timestamps back exactly as Postgres formatted them.
//
// By default node-postgres turns a DATE into a JavaScript Date at local
// midnight, which JSON.stringify then renders in UTC: the date 2025-06-01
// comes out as "2025-05-31T22:00:00.000Z" in Berlin. An agent reading that
// will report June's figure as May. Keeping the server's own text is
// unambiguous and needs no timezone reasoning downstream.
pg.types.setTypeParser(pg.types.builtins.DATE, (v) => v);
pg.types.setTypeParser(pg.types.builtins.TIMESTAMP, (v) => v);
pg.types.setTypeParser(pg.types.builtins.TIMESTAMPTZ, (v) => v);

export const pool = new pg.Pool({
  connectionString: config.databaseUrl,
  max: 4,
  idleTimeoutMillis: 30_000,
  connectionTimeoutMillis: 10_000,
  // Applied per connection; the role also sets this server-side.
  statement_timeout: config.queryTimeoutMs,
  application_name: "netzanalyst-mcp",
});

pool.on("error", (err) => {
  console.error("[db] idle client error:", err.message);
});

export interface QueryResult {
  rows: Record<string, unknown>[];
  rowCount: number;
  fields: { name: string; dataType: string }[];
  elapsedMs: number;
}

/**
 * Run a single read-only query inside an explicit READ ONLY transaction.
 * Even if the SQL guard were bypassed and the role were misconfigured, the
 * transaction itself would reject any write.
 */
export async function runReadOnly(
  sql: string,
  params: unknown[] = [],
): Promise<QueryResult> {
  const started = Date.now();
  const client = await pool.connect();
  try {
    await client.query("BEGIN READ ONLY");
    const result = await client.query({ text: sql, values: params });
    await client.query("COMMIT");
    return {
      rows: result.rows,
      rowCount: result.rowCount ?? result.rows.length,
      fields: result.fields.map((f) => ({
        name: f.name,
        dataType: String(f.dataTypeID),
      })),
      elapsedMs: Date.now() - started,
    };
  } catch (error) {
    try {
      await client.query("ROLLBACK");
    } catch {
      // The connection is already unusable; the pool will discard it.
    }
    throw error;
  } finally {
    client.release();
  }
}

/** Introspect tables, columns and comments so agents can write correct SQL. */
export async function describeSchema(): Promise<string> {
  const objects = await runReadOnly(`
    SELECT c.relname                                   AS name,
           CASE c.relkind WHEN 'r' THEN 'table' ELSE 'view' END AS kind,
           obj_description(c.oid)                      AS comment
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = 'public'
      AND c.relkind IN ('r', 'v')
    -- Tables first, then views: the base tables define the data model and the
    -- views are conveniences layered on top.
    ORDER BY c.relkind ASC, c.relname
  `);

  const columns = await runReadOnly(`
    SELECT c.table_name,
           c.column_name,
           c.data_type,
           c.is_nullable,
           col_description(format('public.%I', c.table_name)::regclass::oid,
                           c.ordinal_position) AS comment
    FROM information_schema.columns c
    WHERE c.table_schema = 'public'
    ORDER BY c.table_name, c.ordinal_position
  `);

  const byTable = new Map<string, Record<string, unknown>[]>();
  for (const row of columns.rows) {
    const table = String(row["table_name"]);
    if (!byTable.has(table)) byTable.set(table, []);
    byTable.get(table)!.push(row);
  }

  const lines: string[] = [];
  for (const obj of objects.rows) {
    const name = String(obj["name"]);
    lines.push(`${String(obj["kind"]).toUpperCase()} ${name}`);
    if (obj["comment"]) lines.push(`  -- ${String(obj["comment"]).replace(/\s+/g, " ")}`);
    for (const col of byTable.get(name) ?? []) {
      const nullable = col["is_nullable"] === "YES" ? "" : " NOT NULL";
      const comment = col["comment"] ? `  -- ${String(col["comment"]).replace(/\s+/g, " ")}` : "";
      lines.push(`    ${String(col["column_name"]).padEnd(22)} ${String(col["data_type"])}${nullable}${comment}`);
    }
    lines.push("");
  }
  return lines.join("\n").trimEnd();
}
