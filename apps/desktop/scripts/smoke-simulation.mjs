// M1 AI Town smoke — create run → advance 1 tick → verify agent moved + decision events.
//
// Requires:
//   - Backend on SMOKE_API (default http://localhost:8000) with SIMULATION_ENABLED=true
//   - Seeded dev user (uv run python scripts/seed_dev_user.py)
//   - Runs are created with scripted:true (no real LLM). Pass --mock to skip tick advancement.
//
// Run:
//   node apps/desktop/scripts/smoke-simulation.mjs
//   node apps/desktop/scripts/smoke-simulation.mjs --mock
//
// Env:
//   SMOKE_API              backend base (default http://localhost:8000)
//   SMOKE_USER/PASS        login creds (default dev / devpassword)
//   SMOKE_TICK_TIMEOUT_MS  wait for tick response (default 120000)

import { mkdir, rm, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const outDir = resolve(here, "../smoke-out");

const API = process.env.SMOKE_API ?? "http://localhost:8000";
const USER = process.env.SMOKE_USER ?? "dev";
const PASS = process.env.SMOKE_PASS ?? "devpassword";
const MOCK_ONLY =
  process.env.SMOKE_MOCK === "1" || process.argv.includes("--mock");
const TICK_TIMEOUT_MS = Number(process.env.SMOKE_TICK_TIMEOUT_MS ?? 120_000);

const summary = {
  api: API,
  mockOnly: MOCK_ONLY,
  authed: false,
  runCreated: false,
  sseConnected: false,
  tickAdvanced: false,
  agentMoved: false,
  decisionSeen: false,
  errors: [],
  ok: false,
};

const cookies = new Map();
let csrfToken = null;

function fail(msg) {
  summary.errors.push(msg);
  throw new Error(msg);
}

function storeCookies(response) {
  const setCookies = response.headers.getSetCookie?.() ?? [];
  for (const raw of setCookies) {
    const [kv] = raw.split(";");
    const eq = kv.indexOf("=");
    if (eq <= 0) continue;
    cookies.set(kv.slice(0, eq).trim(), kv.slice(eq + 1).trim());
  }
}

function captureCsrf(response) {
  const token = response.headers.get("X-CSRF-Token");
  if (token) csrfToken = token;
}

function authHeaders(method = "GET", extra = {}) {
  const headers = { ...extra };
  const cookie = [...cookies.entries()].map(([k, v]) => `${k}=${v}`).join("; ");
  if (cookie) headers.Cookie = cookie;
  if (
    csrfToken &&
    method !== "GET" &&
    method !== "HEAD" &&
    method !== "OPTIONS"
  ) {
    headers["X-CSRF-Token"] = csrfToken;
  }
  headers["X-Client-Platform"] = "desktop";
  return headers;
}

async function apiFetch(path, { method = "GET", body } = {}) {
  const headers = authHeaders(method, {
    Accept: "application/json",
    ...(body ? { "Content-Type": "application/json" } : {}),
  });
  const res = await fetch(`${API}${path}`, {
    method,
    headers,
    body: body ? JSON.stringify(body) : undefined,
  });
  storeCookies(res);
  captureCsrf(res);
  return res;
}

async function login() {
  const res = await apiFetch("/v1/auth/login", {
    method: "POST",
    body: { username: USER, password: PASS },
  });
  if (!res.ok) fail(`login failed (${res.status}): ${await res.text()}`);
  summary.authed = true;
}

async function createRun() {
  const res = await apiFetch("/v1/simulation/runs", {
    method: "POST",
    body: { scenario: "town", seed: 1, scripted: true },
  });
  if (res.status === 404) {
    fail("simulation routes 404 — set SIMULATION_ENABLED=true on backend");
  }
  if (!res.ok) fail(`create run failed (${res.status}): ${await res.text()}`);
  summary.runCreated = true;
  return res.json();
}

function parseSseFrames(buffer, onEvent) {
  const parts = buffer.split("\n\n");
  const rest = parts.pop() ?? "";
  for (const frame of parts) {
    const dataLine = frame.split("\n").find((l) => l.startsWith("data:"));
    if (!dataLine) continue;
    const json = dataLine.replace(/^data:\s?/, "");
    try {
      onEvent(JSON.parse(json));
    } catch {
      /* ignore */
    }
  }
  return rest;
}

async function tailSse(runId, onEvent, signal) {
  const res = await fetch(
    `${API}/v1/simulation/runs/${encodeURIComponent(runId)}/stream`,
    {
      method: "GET",
      headers: authHeaders("GET", { Accept: "text/event-stream" }),
      signal,
    },
  );
  if (!res.ok || !res.body) fail(`SSE connect failed (${res.status})`);
  summary.sseConnected = true;

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    buffer = parseSseFrames(buffer, onEvent);
  }
}

async function advanceTick(runId) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), TICK_TIMEOUT_MS);
  try {
    const res = await fetch(
      `${API}/v1/simulation/runs/${encodeURIComponent(runId)}/tick`,
      {
        method: "POST",
        headers: authHeaders("POST", { "Content-Type": "application/json" }),
        body: "{}",
        signal: controller.signal,
      },
    );
    storeCookies(res);
    captureCsrf(res);
    if (!res.ok)
      fail(`advance tick failed (${res.status}): ${await res.text()}`);
    const body = await res.json();
    summary.tickAdvanced = true;
    return body.snapshot;
  } finally {
    clearTimeout(timer);
  }
}

async function main() {
  await rm(outDir, { recursive: true, force: true });
  await mkdir(outDir, { recursive: true });

  const ready = await fetch(`${API}/readyz`).catch(() => null);
  if (!ready?.ok) fail(`backend not reachable at ${API}`);

  await login();

  const run = await createRun();
  const runId = run.id;

  let agentState = null;
  let decision = null;

  const sseAbort = new AbortController();
  const ssePromise = tailSse(
    runId,
    (event) => {
      if (event.type === "sim.agent_state") {
        agentState = event.payload?.state ?? null;
      }
      if (event.type === "sim.agent_action") {
        decision = event.payload?.action ?? null;
      }
    },
    sseAbort.signal,
  );

  if (MOCK_ONLY) {
    // Let the SSE handshake complete before we tear down (mock skips tick).
    await new Promise((r) => setTimeout(r, 500));
  } else {
    const snapshot = await advanceTick(runId);
    await new Promise((r) => setTimeout(r, 800));
    const lin = snapshot?.agents?.lin;
    if (lin?.location === "市场" || lin?.position?.x === 24) {
      summary.agentMoved = true;
    }
    if (decision?.thought || decision?.detail) {
      summary.decisionSeen = true;
    }
    if (agentState?.location === "市场") {
      summary.agentMoved = true;
    }
  }

  sseAbort.abort();
  await ssePromise.catch(() => {});

  if (MOCK_ONLY) {
    summary.ok = summary.runCreated && summary.sseConnected;
  } else {
    summary.ok =
      summary.tickAdvanced && (summary.agentMoved || summary.decisionSeen);
  }

  await writeFile(
    resolve(outDir, "simulation-smoke.json"),
    JSON.stringify(summary, null, 2),
  );

  if (!summary.ok) {
    console.error(JSON.stringify(summary, null, 2));
    process.exit(1);
  }
  console.log(JSON.stringify(summary, null, 2));
}

main().catch(async (err) => {
  summary.errors.push(err.message);
  await writeFile(
    resolve(outDir, "simulation-smoke.json"),
    JSON.stringify(summary, null, 2),
  ).catch(() => {});
  console.error(err);
  process.exit(1);
});
