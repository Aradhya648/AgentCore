/**
 * Static file server for AgentTown WebGL builds.
 *
 * Unity WebGL builds ship pre-compressed artifacts (WebGL.framework.js.gz,
 * WebGL.wasm.gz, WebGL.data.gz). The loader requests those `.gz` URLs directly
 * and relies on the host sending `Content-Encoding: gzip` so the browser
 * decompresses them transparently. `npx serve` does NOT set that header, which
 * makes Unity fail with "Unable to parse Build/WebGL.framework.js.gz!". This
 * server sets the encoding + the underlying Content-Type, so the build boots.
 *
 * Usage (repo root or anywhere):
 *   node apps/town/scripts/serve-webgl.mjs                 # serve Builds/WebGL, pick 8080→4173, open Offline Demo
 *   node apps/town/scripts/serve-webgl.mjs --pack festival # different story pack (price_surge|festival|town_hall)
 *   node apps/town/scripts/serve-webgl.mjs --no-open       # serve only, do not open a browser
 *   node apps/town/scripts/serve-webgl.mjs --open "<url>"  # open a specific URL (e.g. live ?api=&token=&run=)
 *   node apps/town/scripts/serve-webgl.mjs --port 8080 --strict-port --no-open   # bind exactly :8080 (spike; CORS-listed)
 *
 * Flags:
 *   --root <dir>     directory to serve (default: <script>/../Builds/WebGL)
 *   --port <n>       preferred port (default 8080; falls back to 4173 unless --strict-port)
 *   --strict-port    bind exactly --port; fail if busy (no fallback)
 *   --host <h>       bind host (default 127.0.0.1)
 *   --pack <id>      story pack for the Offline Demo URL (default price_surge)
 *   --open <url>     open this URL after listening (default: the Offline Demo URL)
 *   --no-open        do not open any browser
 */

import { createServer } from "node:http";
import { spawn } from "node:child_process";
import { dirname, resolve, join, relative, sep, isAbsolute } from "node:path";
import { fileURLToPath } from "node:url";
import { existsSync, createReadStream, statSync } from "node:fs";

const here = dirname(fileURLToPath(import.meta.url));

function parseArgs(argv) {
  const out = {};
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (!a.startsWith("--")) continue;
    const key = a.slice(2);
    const next = argv[i + 1];
    if (next === undefined || next.startsWith("--")) {
      out[key] = true;
    } else {
      out[key] = next;
      i++;
    }
  }
  return out;
}

const args = parseArgs(process.argv.slice(2));
const root = resolve(
  typeof args.root === "string" ? args.root : join(here, "..", "Builds", "WebGL"),
);
const host = typeof args.host === "string" ? args.host : "127.0.0.1";
const preferredPort = Number(args.port || 8080);
const strictPort = !!args["strict-port"];
const pack = (typeof args.pack === "string" ? args.pack : "price_surge")
  .trim()
  .toLowerCase();
const openMode = args["no-open"]
  ? null
  : typeof args.open === "string"
    ? args.open
    : "demo";

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "application/javascript",
  ".mjs": "application/javascript",
  ".wasm": "application/wasm",
  ".json": "application/json",
  ".data": "application/octet-stream",
  ".mem": "application/octet-stream",
  ".symbols": "application/octet-stream",
  ".css": "text/css",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".jpeg": "image/jpeg",
  ".svg": "image/svg+xml",
  ".ico": "image/x-icon",
  ".unityweb": "application/octet-stream",
};

function contentType(filePath) {
  const lower = filePath.toLowerCase();
  for (const [ext, type] of Object.entries(MIME)) {
    if (lower.endsWith(ext)) return type;
  }
  return "application/octet-stream";
}

/** Unity gzip/br builds need Content-Encoding so the browser decompresses before the loader parses. */
function responseHeaders(filePath) {
  const lower = filePath.toLowerCase();
  const headers = {
    "Cache-Control": "no-cache",
    "Access-Control-Allow-Origin": "*",
  };
  if (lower.endsWith(".gz")) {
    headers["Content-Encoding"] = "gzip";
    headers["Content-Type"] = contentType(lower.slice(0, -3));
    return headers;
  }
  if (lower.endsWith(".br")) {
    headers["Content-Encoding"] = "br";
    headers["Content-Type"] = contentType(lower.slice(0, -3));
    return headers;
  }
  headers["Content-Type"] = contentType(lower);
  return headers;
}

function isInsideRoot(rootDir, filePath) {
  const rel = relative(rootDir, filePath);
  // Reject traversal ("..") and absolute/drive-relative escapes (Windows).
  return rel !== ".." && !rel.startsWith(`..${sep}`) && !isAbsolute(rel);
}

function createStaticServer(rootDir) {
  return createServer((req, res) => {
    try {
      const url = new URL(req.url || "/", `http://${host}`);
      let rel;
      try {
        rel = decodeURIComponent(url.pathname);
      } catch {
        res.writeHead(400);
        res.end("bad request");
        return;
      }
      if (rel === "/") rel = "/index.html";
      const filePath = resolve(rootDir, "." + rel);
      if (
        !isInsideRoot(rootDir, filePath) ||
        !existsSync(filePath) ||
        statSync(filePath).isDirectory()
      ) {
        res.writeHead(404);
        res.end("not found");
        return;
      }
      res.writeHead(200, responseHeaders(filePath));
      createReadStream(filePath).pipe(res);
    } catch (e) {
      res.writeHead(500);
      res.end(String(e?.message || e));
    }
  });
}

function listen(server, port) {
  return new Promise((resolveListen, reject) => {
    const onError = (e) => {
      server.removeListener("error", onError);
      reject(e);
    };
    server.once("error", onError);
    server.listen(port, host, () => {
      server.removeListener("error", onError);
      resolveListen(port);
    });
  });
}

async function listenFirstAvailable(server, ports) {
  let lastErr;
  for (const port of ports) {
    try {
      return await listen(server, port);
    } catch (e) {
      lastErr = e;
      if (e?.code === "EADDRINUSE") {
        console.warn(`port ${port} busy — trying next`);
        continue;
      }
      throw e;
    }
  }
  throw lastErr || new Error(`No free port among ${ports.join(", ")}`);
}

function openBrowser(url) {
  try {
    if (process.platform === "win32") {
      spawn("cmd", ["/c", "start", "", url], {
        detached: true,
        stdio: "ignore",
      }).unref();
    } else if (process.platform === "darwin") {
      spawn("open", [url], { detached: true, stdio: "ignore" }).unref();
    } else {
      spawn("xdg-open", [url], { detached: true, stdio: "ignore" }).unref();
    }
  } catch {
    /* best-effort */
  }
}

async function main() {
  const index = join(root, "index.html");
  if (!existsSync(index)) {
    console.error(
      `WebGL build missing: ${index}\nRun first: pnpm town:build:webgl`,
    );
    process.exit(1);
  }

  const candidates = strictPort
    ? [preferredPort]
    : [...new Set([preferredPort, 8080, 4173])];

  const server = createStaticServer(root);
  let port;
  try {
    port = await listenFirstAvailable(server, candidates);
  } catch (e) {
    console.error(
      `Could not bind static server on ${candidates.join(", ")}: ${e?.message || e}`,
    );
    process.exit(1);
  }

  const base = `http://${host}:${port}`;
  const demoUrl = `${base}/?demo=1&pack=${pack}`;

  console.log("");
  console.log("=== AgentTown WebGL server ===");
  console.log(`Serving ${root}`);
  console.log(`Offline Demo: ${demoUrl}`);
  console.log(`Packs:        ${base}/?demo=1&pack=festival  (or town_hall; default price_surge)`);
  console.log(`Live (needs backend): ${base}/?api=http%3A%2F%2Flocalhost%3A8000&token=TOKEN&run=RUN_ID`);
  console.log(`LISTENING ${base}`);
  console.log("");

  if (openMode) {
    const url = openMode === "demo" ? demoUrl : openMode;
    openBrowser(url);
    console.log(`Opened browser → ${url}`);
  }

  console.log("Press Ctrl+C to stop the static server.");

  const shutdown = () => {
    server.close(() => process.exit(0));
    setTimeout(() => process.exit(0), 500).unref();
  };
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
}

main().catch((e) => {
  console.error(String(e?.stack || e));
  process.exit(1);
});
