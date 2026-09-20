import { test } from "node:test";
import assert from "node:assert/strict";
import { guardSelect, SqlGuardError } from "./sql-guard.js";

const MAX = 1000;

const rejects = (sql: string, because: string): void => {
  assert.throws(() => guardSelect(sql, MAX), SqlGuardError, `should reject: ${because}`);
};

test("accepts a plain SELECT and adds a LIMIT", () => {
  const r = guardSelect("SELECT * FROM generation", MAX);
  assert.equal(r.limitApplied, true);
  assert.equal(r.limit, MAX);
  assert.match(r.sql, /LIMIT 1000$/);
});

test("accepts a CTE", () => {
  const r = guardSelect("WITH x AS (SELECT 1 AS n) SELECT n FROM x", MAX);
  assert.ok(r.sql.startsWith("WITH"));
});

test("keeps a caller LIMIT that is within the cap", () => {
  const r = guardSelect("SELECT 1 LIMIT 10", MAX);
  assert.equal(r.limitApplied, false);
  assert.equal(r.limit, 10);
  assert.ok(!/LIMIT 1000/.test(r.sql));
});

test("rejects a LIMIT above the cap", () => {
  rejects("SELECT * FROM generation LIMIT 999999", "LIMIT exceeds the cap");
});

test("strips a single trailing semicolon", () => {
  const r = guardSelect("SELECT 1;", MAX);
  assert.ok(!r.sql.includes(";"));
});

test("rejects write statements", () => {
  for (const sql of [
    "INSERT INTO generation VALUES (now(), 'solar', 1)",
    "UPDATE generation SET mwh = 0",
    "DELETE FROM generation",
    "DROP TABLE generation",
    "TRUNCATE generation",
    "ALTER TABLE generation ADD COLUMN x int",
    "CREATE TABLE evil (i int)",
    "GRANT ALL ON generation TO PUBLIC",
  ]) {
    rejects(sql, sql);
  }
});

test("rejects stacked statements", () => {
  rejects("SELECT 1; DROP TABLE generation", "two statements");
  rejects("SELECT 1; SELECT 2", "two SELECTs is still two statements");
});

test("rejects a write hidden after a line comment", () => {
  rejects("SELECT 1 -- harmless\n; DROP TABLE generation", "comment then write");
});

test("rejects a write hidden after a block comment", () => {
  rejects("SELECT 1 /* note */ ; DELETE FROM price", "block comment then write");
});

test("rejects nested block comments used to smuggle a statement", () => {
  rejects("SELECT 1 /* a /* b */ still comment */ ; DROP TABLE price", "nested comments");
});

test("a semicolon inside a string literal is not a statement separator", () => {
  const r = guardSelect("SELECT 'a;b' AS s", MAX);
  assert.ok(r.sql.includes("'a;b'"), "the literal must survive untouched");
});

test("a forbidden keyword inside a string literal is allowed", () => {
  const r = guardSelect("SELECT 'delete me' AS label", MAX);
  assert.ok(r.sql.includes("'delete me'"));
});

test("a forbidden keyword inside a quoted identifier is allowed", () => {
  const r = guardSelect('SELECT "drop" FROM generation', MAX);
  assert.ok(r.sql.includes('"drop"'));
});

test("does not trip on identifiers that merely contain a keyword", () => {
  // "created_at" contains "create"; "updated_at" contains "update".
  const r = guardSelect("SELECT created_at, updated_at FROM ingest_log", MAX);
  assert.ok(r.sql.includes("created_at"));
});

test("rejects filesystem and sleep functions", () => {
  rejects("SELECT pg_read_file('/etc/passwd')", "file read");
  rejects("SELECT pg_sleep(30)", "sleep");
  rejects("SELECT pg_ls_dir('/')", "directory listing");
  rejects("SELECT lo_import('/etc/passwd')", "large-object import");
});

test("rejects an empty or whitespace query", () => {
  rejects("", "empty");
  rejects("   \n  ", "whitespace only");
});

test("rejects a non-SELECT leading keyword", () => {
  rejects("EXPLAIN ANALYZE SELECT 1", "EXPLAIN ANALYZE runs the query");
  rejects("COPY generation TO '/tmp/x.csv'", "COPY writes files");
  rejects("SET statement_timeout = 0", "SET changes session state");
});

test("dollar-quoted bodies cannot smuggle a statement", () => {
  rejects("SELECT $$x$$ ; DROP TABLE price", "dollar quote then write");
});

test("realistic analytical query passes", () => {
  const sql = `
    SELECT month_berlin, renewable_pct
    FROM v_renewable_share_monthly
    WHERE month_berlin >= DATE '2025-01-01'
    ORDER BY month_berlin
  `;
  const r = guardSelect(sql, MAX);
  assert.equal(r.limitApplied, true);
});
