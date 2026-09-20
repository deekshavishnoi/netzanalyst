/** Configuration, read once at startup from the environment. */

function required(name: string): string {
  const value = process.env[name];
  if (!value) {
    throw new Error(
      `${name} is not set. Copy .env.example to .env and fill it in.`,
    );
  }
  return value;
}

function int(name: string, fallback: number): number {
  const raw = process.env[name];
  if (!raw) return fallback;
  const parsed = Number.parseInt(raw, 10);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    throw new Error(`${name} must be a positive integer, got "${raw}"`);
  }
  return parsed;
}

export const config = {
  /**
   * Connection string for the READ-ONLY database role.
   * The server must never be given the owner role: the SQL guard in
   * sql-guard.ts is the first line of defence, and this role is the second.
   */
  databaseUrl: required("DATABASE_URL_READONLY"),
  port: int("MCP_PORT", 3000),
  /** Hard cap on rows returned by run_sql, enforced by rewriting the query. */
  maxRows: int("MCP_MAX_ROWS", 1000),
  /** Per-query statement timeout, in milliseconds. */
  queryTimeoutMs: int("MCP_QUERY_TIMEOUT_MS", 10_000),
  energyChartsBaseUrl:
    process.env.ENERGY_CHARTS_BASE_URL ?? "https://api.energy-charts.info",
} as const;
