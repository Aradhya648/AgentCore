// INT-05: AI Town end-to-end smoke — exercises the full simulation REST + SSE contract
// as a live regression guard (ST-02): create → manifest → inject → patch → pause/resume →
// N ticks → SSE tail → tick readback → metrics → replay. Each response is shape-checked
// against the frozen contract (the committed sim.* conformance vectors are the golden shapes).
//
// Requires:
//   - Backend on SMOKE_API (default http://localhost:8000) with SIMULATION_ENABLED=true
//   - Seeded dev user (uv run python scripts/seed_dev_user.py)
//   - Runs are created with scripted:true (no real LLM). Set SMOKE_MOCK=1 to skip tick advancement.
//
// Run:
//   pnpm -C apps/desktop sim:smoke:e2e
//   node apps/desktop/scripts/smoke-simulation-e2e.mjs
//
// Env:
//   SMOKE_API              backend base (default http://localhost:8000)
//   SMOKE_USER/PASS        login creds (default dev / devpassword)
//   SMOKE_TICKS            ticks to advance (default 3)
//   SMOKE_TICK_TIMEOUT_MS  per-tick timeout (default 120000)
//   SMOKE_MOCK=1           skip tick advancement; verify create + SSE only

import { mkdir, rm, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const outDir = resolve(here, "../smoke-out");

const API = process.env.SMOKE_API ?? "http://localhost:8000";
const USER = process.env.SMOKE_USER ?? "dev";
const PASS = process.env.SMOKE_PASS ?? "devpassword";
const TICK_COUNT = Number(process.env.SMOKE_TICKS ?? 3);
const TICK_TIMEOUT_MS = Number(process.env.SMOKE_TICK_TIMEOUT_MS ?? 120_000);
const MOCK_ONLY =
  process.env.SMOKE_MOCK === "1" || process.argv.includes("--mock");

const summary = {
  api: API,
  mockOnly: MOCK_ONLY,
  tickCount: TICK_COUNT,
  authed: false,
  runCreated: false,
  sseConnected: false,
  manifestOk: false,
  pauseResumeOk: false,
  injectOk: false,
  patchOk: false,
  ticksAdvanced: 0,
  tickReadbackOk: false,
  metricsOk: false,
  replayOk: false,
  sseEventTypes: [],
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
    body: { scenario: "town", seed: 42, scripted: true },
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
    return res.json();
  } finally {
    clearTimeout(timer);
  }
}

async function readTick(runId, tickNumber) {
  const res = await apiFetch(
    `/v1/simulation/runs/${encodeURIComponent(runId)}/ticks/${tickNumber}`,
  );
  if (!res.ok)
    fail(`read tick ${tickNumber} failed (${res.status}): ${await res.text()}`);
  return res.json();
}

/** Assert `obj` carries every key in `fields` (shape guard against the frozen contract). */
function requireFields(obj, fields, label) {
  if (!obj || typeof obj !== "object") fail(`${label}: not an object`);
  for (const field of fields) {
    if (!(field in obj)) fail(`${label}: missing field '${field}'`);
  }
}

async function getManifest(runId) {
  const res = await apiFetch(
    `/v1/simulation/runs/${encodeURIComponent(runId)}/manifest`,
  );
  if (!res.ok) fail(`get manifest failed (${res.status}): ${await res.text()}`);
  const body = await res.json();
  requireFields(body, ["run_id", "manifest"], "manifest");
  requireFields(
    body.manifest,
    ["manifest_version", "scenario", "seed", "personas", "regions"],
    "manifest.manifest",
  );
  summary.manifestOk = true;
}

async function pauseResume(runId) {
  const pause = await apiFetch(
    `/v1/simulation/runs/${encodeURIComponent(runId)}/pause`,
    { method: "POST", body: {} },
  );
  if (!pause.ok) fail(`pause failed (${pause.status}): ${await pause.text()}`);
  const paused = await pause.json();
  requireFields(paused, ["run_id", "status", "current_tick"], "pause");
  if (paused.status !== "paused")
    fail(`expected status paused, got ${paused.status}`);

  const resume = await apiFetch(
    `/v1/simulation/runs/${encodeURIComponent(runId)}/resume`,
    { method: "POST", body: {} },
  );
  if (!resume.ok)
    fail(`resume failed (${resume.status}): ${await resume.text()}`);
  const resumed = await resume.json();
  requireFields(resumed, ["run_id", "status", "current_tick"], "resume");
  summary.pauseResumeOk = true;
}

async function injectEvent(runId) {
  const res = await apiFetch(
    `/v1/simulation/runs/${encodeURIComponent(runId)}/inject`,
    {
      method: "POST",
      body: { event_type: "announcement", payload: { title: "冒烟通告" } },
    },
  );
  if (res.status !== 202)
    fail(`inject failed (${res.status}): ${await res.text()}`);
  const body = await res.json();
  requireFields(
    body,
    ["run_id", "event_id", "event_type", "title", "queued_for_tick"],
    "inject",
  );
  summary.injectOk = true;
}

async function patchAgent(runId, agentId) {
  const res = await apiFetch(
    `/v1/simulation/runs/${encodeURIComponent(runId)}/agents/${encodeURIComponent(agentId)}`,
    { method: "PATCH", body: { goal: "冒烟：今天多烤两炉面包" } },
  );
  if (!res.ok) fail(`patch agent failed (${res.status}): ${await res.text()}`);
  const body = await res.json();
  requireFields(body, ["run_id", "agent_id", "state"], "patch");
  requireFields(
    body.state,
    ["agent_id", "name", "location", "position"],
    "patch.state",
  );
  summary.patchOk = true;
}

async function getMetrics(runId, expectedLen) {
  const res = await apiFetch(
    `/v1/simulation/runs/${encodeURIComponent(runId)}/metrics`,
  );
  if (!res.ok) fail(`get metrics failed (${res.status}): ${await res.text()}`);
  const body = await res.json();
  requireFields(body, ["run_id", "metrics"], "metrics");
  if (!Array.isArray(body.metrics)) fail("metrics.metrics is not an array");
  if (body.metrics.length !== expectedLen) {
    fail(`expected ${expectedLen} metric rows, got ${body.metrics.length}`);
  }
  if (body.metrics.length > 0) {
    requireFields(
      body.metrics[0],
      ["tick", "hour", "avg_mood", "trade_count", "population_by_region"],
      "metrics[0]",
    );
  }
  summary.metricsOk = true;
}

async function replayRange(runId, fromTick, toTick) {
  const res = await fetch(
    `${API}/v1/simulation/runs/${encodeURIComponent(runId)}/replay?from=${fromTick}&to=${toTick}`,
    {
      method: "GET",
      headers: authHeaders("GET", { Accept: "text/event-stream" }),
    },
  );
  if (!res.ok || !res.body) fail(`replay failed (${res.status})`);
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  const seen = [];
  let buffer = "";
  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });
    buffer = parseSseFrames(buffer, (event) => {
      if (event?.type) seen.push(event.type);
    });
  }
  if (!seen.some((t) => t.startsWith("sim."))) {
    fail("replay produced no sim.* events");
  }
  if (!seen.includes("sim.tick_frame")) {
    fail("replay missing trailing sim.tick_frame snapshot");
  }
  summary.replayOk = true;
}

async function main() {
  await rm(outDir, { recursive: true, force: true });
  await mkdir(outDir, { recursive: true });

  const ready = await fetch(`${API}/readyz`).catch(() => null);
  if (!ready?.ok) fail(`backend not reachable at ${API}`);

  await login();
  const run = await createRun();
  const runId = run.id;

  // REST contract guards that need no LLM — run in both mock and live modes.
  await getManifest(runId);
  await injectEvent(runId);
  await patchAgent(runId, "lin");
  await pauseResume(runId);

  const seenTypes = new Set();
  const sseAbort = new AbortController();
  const ssePromise = tailSse(
    runId,
    (event) => {
      if (event?.type) seenTypes.add(event.type);
    },
    sseAbort.signal,
  );

  if (MOCK_ONLY) {
    await new Promise((r) => setTimeout(r, 500));
  } else {
    for (let tick = 1; tick <= TICK_COUNT; tick += 1) {
      const body = await advanceTick(runId);
      const snapshotTick = body?.snapshot?.tick;
      if (snapshotTick !== tick) {
        fail(`expected snapshot tick ${tick}, got ${snapshotTick}`);
      }
      summary.ticksAdvanced += 1;
    }
    await new Promise((r) => setTimeout(r, 500));

    const frame = await readTick(runId, 1);
    if (frame.tick_number !== 1 || !frame.snapshot) {
      fail("tick readback missing snapshot for tick 1");
    }
    summary.tickReadbackOk = true;

    await getMetrics(runId, TICK_COUNT);
    await replayRange(runId, 1, TICK_COUNT);
  }

  sseAbort.abort();
  await ssePromise.catch(() => {});
  summary.sseEventTypes = [...seenTypes].sort();

  const restOk =
    summary.manifestOk &&
    summary.pauseResumeOk &&
    summary.injectOk &&
    summary.patchOk;

  if (MOCK_ONLY) {
    summary.ok = summary.runCreated && summary.sseConnected && restOk;
  } else {
    const sawSimEvent = summary.sseEventTypes.some((t) => t.startsWith("sim."));
    summary.ok =
      summary.ticksAdvanced === TICK_COUNT &&
      summary.tickReadbackOk &&
      summary.sseConnected &&
      sawSimEvent &&
      restOk &&
      summary.metricsOk &&
      summary.replayOk;
    if (!sawSimEvent) {
      summary.errors.push("no sim.* SSE events observed");
    }
  }

  await writeFile(
    resolve(outDir, "simulation-e2e-smoke.json"),
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
    resolve(outDir, "simulation-e2e-smoke.json"),
    JSON.stringify(summary, null, 2),
  ).catch(() => {});
  console.error(err);
  process.exit(1);
});
