/**
 * Validation for user-supplied SQL before it reaches Postgres.
 *
 * This is defence in depth, not the only defence. The real guarantee is the
 * database role: netzanalyst_ro has SELECT only, `default_transaction_read_only`
 * on, and a server-side statement_timeout. Every query also runs inside an
 * explicit READ ONLY transaction.
 *
 * What this module adds is a fast, legible rejection with a message an LLM can
 * act on, and protection against the two things a read-only role does not stop:
 * multi-statement batches and unbounded result sets.
 */

export class SqlGuardError extends Error {
  constructor(message: string) {
    super(message);
    this.name = "SqlGuardError";
  }
}

/**
 * Replace string literals, dollar-quoted blocks and comments with spaces of the
 * same length, so keyword and semicolon scanning cannot be fooled by a
 * semicolon or the word "delete" inside a quoted string.
 */
function blankOutLiteralsAndComments(sql: string): string {
  const out = sql.split("");
  let i = 0;

  const blank = (from: number, to: number): void => {
    for (let k = from; k < to && k < out.length; k++) {
      if (out[k] !== "\n") out[k] = " ";
    }
  };

  while (i < sql.length) {
    const two = sql.slice(i, i + 2);

    if (two === "--") {
      const end = sql.indexOf("\n", i);
      const stop = end === -1 ? sql.length : end;
      blank(i, stop);
      i = stop;
      continue;
    }

    if (two === "/*") {
      // Postgres block comments nest.
      let depth = 1;
      let j = i + 2;
      while (j < sql.length && depth > 0) {
        if (sql.slice(j, j + 2) === "/*") { depth++; j += 2; }
        else if (sql.slice(j, j + 2) === "*/") { depth--; j += 2; }
        else j++;
      }
      blank(i, j);
      i = j;
      continue;
    }

    if (sql[i] === "'" || sql[i] === '"') {
      const quote = sql[i]!;
      let j = i + 1;
      while (j < sql.length) {
        if (sql[j] === quote) {
          if (sql[j + 1] === quote) { j += 2; continue; } // escaped by doubling
          j++;
          break;
        }
        j++;
      }
      blank(i + 1, j - 1);
      i = j;
      continue;
    }

    // Dollar quoting: $tag$ ... $tag$
    if (sql[i] === "$") {
      const match = /^\$[A-Za-z_]*\$/.exec(sql.slice(i));
      if (match) {
        const tag = match[0];
        const close = sql.indexOf(tag, i + tag.length);
        const stop = close === -1 ? sql.length : close + tag.length;
        blank(i, stop);
        i = stop;
        continue;
      }
    }

    i++;
  }

  return out.join("");
}

/**
 * Statements and functions that must never run, even though the read-only role
 * would already reject most of them. Listed explicitly so the error message
 * tells the agent what it did wrong instead of surfacing a Postgres error.
 */
const FORBIDDEN = [
  "insert", "update", "delete", "truncate", "drop", "alter", "create",
  "grant", "revoke", "comment", "copy", "call", "do", "merge",
  "vacuum", "analyze", "reindex", "cluster", "refresh", "listen",
  "notify", "prepare", "execute", "deallocate", "discard", "lock",
  "set", "reset", "begin", "commit", "rollback", "savepoint", "security",
];

/** Functions that read the filesystem, sleep, or reach the network. */
const FORBIDDEN_FUNCTIONS = [
  "pg_read_file", "pg_read_binary_file", "pg_ls_dir", "pg_stat_file",
  "pg_sleep", "pg_sleep_for", "pg_sleep_until",
  "lo_import", "lo_export", "dblink", "pg_logical_emit_message",
  "pg_terminate_backend", "pg_cancel_backend", "pg_reload_conf",
];

export interface GuardedQuery {
  /** The query actually sent to Postgres, with a LIMIT applied. */
  sql: string;
  /** True when this module added a LIMIT the caller did not write. */
  limitApplied: boolean;
  /** The effective row cap. */
  limit: number;
}

export function guardSelect(rawSql: string, maxRows: number): GuardedQuery {
  const sql = rawSql.trim().replace(/;\s*$/, "");
  if (!sql) {
    throw new SqlGuardError("The query is empty.");
  }

  const scannable = blankOutLiteralsAndComments(sql);

  if (scannable.includes(";")) {
    throw new SqlGuardError(
      "Only a single statement is allowed. Remove the ';' and send one SELECT.",
    );
  }

  const firstWord = /^\s*([a-z]+)/i.exec(scannable)?.[1]?.toLowerCase();
  if (firstWord !== "select" && firstWord !== "with") {
    throw new SqlGuardError(
      `Only read queries are allowed: the statement must start with SELECT or WITH, but it starts with "${firstWord ?? "?"}".`,
    );
  }

  const lowered = scannable.toLowerCase();

  for (const word of FORBIDDEN) {
    // \b alone would match "create" inside "created_at"; require a
    // non-identifier character on both sides.
    const re = new RegExp(`(^|[^a-z0-9_])${word}([^a-z0-9_]|$)`, "i");
    if (re.test(lowered)) {
      throw new SqlGuardError(
        `The keyword "${word.toUpperCase()}" is not allowed. This tool runs read-only SELECT queries.`,
      );
    }
  }

  for (const fn of FORBIDDEN_FUNCTIONS) {
    if (new RegExp(`(^|[^a-z0-9_])${fn}\\s*\\(`, "i").test(lowered)) {
      throw new SqlGuardError(`The function ${fn}() is not allowed.`);
    }
  }

  // Wrapping in a subquery would be simpler, but it breaks ORDER BY semantics
  // for some queries and confuses column naming. Appending is predictable.
  const hasLimit = /(^|[^a-z0-9_])limit\s+\d+\s*$/i.test(scannable);
  if (hasLimit) {
    const declared = Number.parseInt(/limit\s+(\d+)\s*$/i.exec(scannable)![1]!, 10);
    if (declared <= maxRows) {
      return { sql, limitApplied: false, limit: declared };
    }
    throw new SqlGuardError(
      `LIMIT ${declared} exceeds the maximum of ${maxRows} rows. Aggregate in SQL instead of returning raw rows.`,
    );
  }

  return { sql: `${sql}\nLIMIT ${maxRows}`, limitApplied: true, limit: maxRows };
}
