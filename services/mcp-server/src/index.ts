/**
 * netzanalyst MCP server.
 *
 * Exposes read-only German electricity data over MCP:
 *   get_schema           tables, columns and usage notes
 *   run_sql              a single guarded read-only SELECT
 *   fetch_energy_charts  recent data straight from Fraunhofer ISE
 *
 * Two transports:
 *   --stdio   for local MCP clients (Claude Desktop, MCP Inspector)
 *   default   streamable HTTP on MCP_PORT, for the agents and for hosting
 */

import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { Readable } from "node:stream";
import {
  McpServer,
  createMcpHandler,
  hostHeaderValidationResponse,
  originValidationResponse,
  localhostAllowedHostnames,
  localhostAllowedOrigins,
} from "@modelcontextprotocol/server";
import { StdioServerTransport } from "@modelcontextprotocol/server/stdio";
import { config } from "./config.js";
import { pool } from "./db.js";
import { registerTools } from "./tools.js";

const SERVER_INFO = { name: "netzanalyst", version: "0.1.0" } as const;

const INSTRUCTIONS =
  "German electricity data: generation, consumption and day-ahead prices. " +
  "Call get_schema first, then run_sql for anything in the database, and " +
  "fetch_energy_charts only for dates newer than the database coverage.";

function buildServer(): McpServer {
  const server = new McpServer(SERVER_INFO, { instructions: INSTRUCTIONS });
  registerTools(server);
  return server;
}

// ---------------------------------------------------------------------------
// stdio
// ---------------------------------------------------------------------------

async function runStdio(): Promise<void> {
  const server = buildServer();
  await server.connect(new StdioServerTransport());
  // stdout is the protocol channel on stdio, so diagnostics go to stderr.
  console.error("netzanalyst MCP server ready on stdio");
}

// ---------------------------------------------------------------------------
// HTTP
// ---------------------------------------------------------------------------

/** Adapt a Node request to a web-standard Request. */
function toWebRequest(req: IncomingMessage): Request {
  const host = req.headers.host ?? `localhost:${config.port}`;
  const url = new URL(req.url ?? "/", `http://${host}`);

  const headers = new Headers();
  for (const [key, value] of Object.entries(req.headers)) {
    if (value === undefined) continue;
    if (Array.isArray(value)) for (const v of value) headers.append(key, v);
    else headers.set(key, value);
  }

  const method = req.method ?? "GET";
  const hasBody = method !== "GET" && method !== "HEAD";
  return new Request(url, {
    method,
    headers,
    body: hasBody ? (Readable.toWeb(req) as ReadableStream<Uint8Array>) : undefined,
    // Required by undici whenever a body is a stream.
    ...(hasBody ? { duplex: "half" } : {}),
  } as RequestInit);
}

/** Write a web-standard Response back to a Node response. */
async function writeWebResponse(response: Response, res: ServerResponse): Promise<void> {
  const headers: Record<string, string | string[]> = {};
  response.headers.forEach((value, key) => {
    if (key.toLowerCase() === "set-cookie") {
      headers[key] = [...(Array.isArray(headers[key]) ? (headers[key] as string[]) : []), value];
    } else {
      headers[key] = value;
    }
  });
  res.writeHead(response.status, headers);

  if (!response.body) {
    res.end();
    return;
  }
  // Streamed so SSE responses reach the client as they are produced.
  const reader = response.body.getReader();
  try {
    for (;;) {
      const { done, value } = await reader.read();
      if (done) break;
      res.write(value);
    }
  } finally {
    res.end();
  }
}

async function runHttp(): Promise<void> {
  const handler = createMcpHandler(() => buildServer());

  const http = createServer((req, res) => {
    void (async () => {
      try {
        if (req.url === "/health") {
          try {
            await pool.query("SELECT 1");
            res.writeHead(200, { "content-type": "application/json" });
            res.end(JSON.stringify({ status: "ok", database: "reachable" }));
          } catch (error) {
            res.writeHead(503, { "content-type": "application/json" });
            res.end(JSON.stringify({ status: "degraded", error: (error as Error).message }));
          }
          return;
        }

        const path = (req.url ?? "/").split("?")[0];
        if (path !== "/mcp") {
          res.writeHead(404, { "content-type": "text/plain" });
          res.end("Not found. MCP is served at /mcp; health at /health.\n");
          return;
        }

        const request = toWebRequest(req);

        // Reject DNS-rebinding attacks: a browser page on another origin must
        // not be able to drive this server just because it is bound locally.
        const rejected =
          hostHeaderValidationResponse(request, localhostAllowedHostnames()) ??
          originValidationResponse(request, localhostAllowedOrigins());
        if (rejected) {
          await writeWebResponse(rejected, res);
          return;
        }

        await writeWebResponse(await handler.fetch(request), res);
      } catch (error) {
        console.error("[http] request failed:", (error as Error).message);
        if (!res.headersSent) {
          res.writeHead(500, { "content-type": "application/json" });
          res.end(JSON.stringify({ error: "internal error" }));
        } else {
          res.end();
        }
      }
    })();
  });

  await new Promise<void>((resolve) => http.listen(config.port, resolve));
  console.error(`netzanalyst MCP server listening on http://localhost:${config.port}/mcp`);

  let closing = false;
  const shutdown = async (signal: string): Promise<void> => {
    if (closing) return;
    closing = true;
    console.error(`\n[${signal}] shutting down`);
    http.close();
    await handler.close();
    await pool.end();
    process.exit(0);
  };
  process.on("SIGINT", () => void shutdown("SIGINT"));
  process.on("SIGTERM", () => void shutdown("SIGTERM"));
}

(process.argv.includes("--stdio") ? runStdio() : runHttp()).catch((error: unknown) => {
  console.error("fatal:", (error as Error).message);
  process.exit(1);
});
