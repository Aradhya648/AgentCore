/**
 * AgentTown WebGL jslib SSE smoke (§15.2).
 *
 * Loads Builds/WebGL with ?api=&token=&run=, wraps fetch to observe the
 * AgentTownSse.jslib stream (Unity status text stays in HUD, not console),
 * and optionally advances a tick so sim.tick_* frames appear.
 *
 * Env:
 *   SPIKE_URL          full page URL (required)
 *   SPIKE_API          API base (for tick), default http://localhost:8000
 *   SPIKE_TOKEN        Bearer token (for tick)
 *   SPIKE_RUN_ID       run id (for tick)
 *   SPIKE_TIMEOUT_MS   default 120000
 *   SPIKE_PLAYWRIGHT   optional absolute path to playwright package root
 *
 * Exit 0 on: SSE HTTP OK + at least one sim.* / tick frame (strict §14.6).
 * Opt-in soft pass: SPIKE_ALLOW_CONNECTED_ONLY=1 → connected with no frames after 45s.
 * Exit 1 on timeout / hard load failure.
 */

import { createRequire } from "node:module";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { existsSync } from "node:fs";

const here = dirname(fileURLToPath(import.meta.url));
const URL = process.env.SPIKE_URL;
const API = process.env.SPIKE_API || "http://localhost:8000";
const TOKEN = process.env.SPIKE_TOKEN || "";
const RUN_ID = process.env.SPIKE_RUN_ID || "";
const TIMEOUT_MS = Number(process.env.SPIKE_TIMEOUT_MS || 120_000);
const ALLOW_CONNECTED_ONLY = process.env.SPIKE_ALLOW_CONNECTED_ONLY === "1";

if (!URL) {
  console.error("FAIL SPIKE_URL required");
  process.exit(1);
}

async function loadChromium() {
  const requirePaths = [];
  if (process.env.SPIKE_PLAYWRIGHT) {
    requirePaths.push(resolve(process.env.SPIKE_PLAYWRIGHT, "package.json"));
  }
  requirePaths.push(resolve(here, "../../desktop/package.json"));
  requirePaths.push(resolve(here, "../../../package.json"));

  for (const pkgJson of requirePaths) {
    if (!existsSync(pkgJson)) continue;
    try {
      const require = createRequire(pkgJson);
      const pw = require("playwright");
      if (pw?.chromium) return pw.chromium;
    } catch {
      /* try next */
    }
  }

  // ESM import fallback (npx / hoisted)
  try {
    const mod = await import("playwright");
    if (mod?.chromium) return mod.chromium;
  } catch {
    /* */
  }

  throw new Error(
    "playwright not found. Install once: pnpm -C apps/desktop exec playwright install chromium\n" +
      "Or: npx --yes -p playwright playwright install chromium",
  );
}

function fail(msg) {
  console.error("FAIL", msg);
  process.exit(1);
}

async function advanceTick() {
  if (!TOKEN || !RUN_ID) return;
  try {
    const r = await fetch(`${API}/v1/simulation/runs/${encodeURIComponent(RUN_ID)}/tick`, {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${TOKEN}`,
      },
      body: "{}",
    });
    console.log("tick status=", r.status);
  } catch (e) {
    console.warn("tick err", String(e?.message || e));
  }
}

async function main() {
  const chromium = await loadChromium();
  const browser = await chromium.launch({ headless: true });
  const page = await browser.newPage();

  const consoleHits = [];
  const fatalHints = [];
  page.on("console", (msg) => {
    const text = msg.text();
    consoleHits.push(text);
    if (
      /ArgumentNullException|NullReferenceException|shader/i.test(text) ||
      /SSE|sim\.|AgentTown|connected|tick_/i.test(text) ||
      msg.type() === "error"
    ) {
      console.log(`[console.${msg.type()}]`, text.slice(0, 240));
    }
    if (/ArgumentNullException|NullReferenceException:\s*Object reference/i.test(text)) {
      fatalHints.push(text.slice(0, 160));
    }
  });
  page.on("pageerror", (err) => {
    const t = String(err);
    console.log("[pageerror]", t.slice(0, 240));
    fatalHints.push(t.slice(0, 160));
  });

  // Observe jslib fetch before Unity boots.
  await page.addInitScript(() => {
    window.__agentTownSpike = {
      sseOpen: false,
      sseHttpOk: false,
      eventTypes: [],
      statuses: [],
      errors: [],
    };
    const orig = window.fetch.bind(window);
    window.fetch = async (input, init) => {
      const url = typeof input === "string" ? input : input && input.url ? input.url : String(input);
      const headers = (init && init.headers) || {};
      const accept =
        typeof headers.get === "function"
          ? headers.get("Accept") || headers.get("accept") || ""
          : headers.Accept || headers.accept || "";
      const isSse =
        url.includes("/stream") || String(accept).toLowerCase().includes("text/event-stream");

      if (!isSse) {
        return orig(input, init);
      }

      window.__agentTownSpike.sseOpen = true;
      try {
        const res = await orig(input, init);
        if (!res.ok || !res.body) {
          window.__agentTownSpike.errors.push(`SSE HTTP ${res.status}`);
          return res;
        }
        window.__agentTownSpike.sseHttpOk = true;
        window.__agentTownSpike.statuses.push("connected");

        const [forUnity, forProbe] = res.body.tee();
        (async () => {
          const reader = forProbe.getReader();
          const dec = new TextDecoder();
          let buf = "";
          for (;;) {
            const { done, value } = await reader.read();
            if (done) break;
            buf += dec.decode(value, { stream: true });
            const parts = buf.split("\n\n");
            buf = parts.pop() || "";
            for (const frame of parts) {
              const dataLine = frame.split("\n").find((l) => l.startsWith("data:"));
              if (!dataLine) continue;
              try {
                const ev = JSON.parse(dataLine.replace(/^data:\s?/, ""));
                const name = ev.type || ev.event || ev.name || "data";
                window.__agentTownSpike.eventTypes.push(String(name));
              } catch {
                window.__agentTownSpike.eventTypes.push("raw");
              }
            }
          }
        })().catch((e) => {
          window.__agentTownSpike.errors.push(String(e && e.message ? e.message : e));
        });

        return new Response(forUnity, {
          status: res.status,
          statusText: res.statusText,
          headers: res.headers,
        });
      } catch (e) {
        window.__agentTownSpike.errors.push(String(e && e.message ? e.message : e));
        throw e;
      }
    };
  });

  console.log("goto", URL);
  const t0 = Date.now();
  await page.goto(URL, { waitUntil: "domcontentloaded", timeout: Math.min(TIMEOUT_MS, 90_000) });

  // Unity WebGL often needs a long boot; canvas is a soft signal.
  try {
    await page.waitForSelector("canvas", { timeout: Math.min(60_000, TIMEOUT_MS) });
    console.log("canvas present");
  } catch {
    console.warn("canvas not found yet — continuing SSE wait");
  }

  // Kick a tick after a short settle so the live stream has something to emit.
  setTimeout(() => {
    advanceTick().catch(() => {});
  }, 8_000);
  // Second tick later in case first raced before SSE connected.
  setTimeout(() => {
    advanceTick().catch(() => {});
  }, 25_000);

  const deadline = t0 + TIMEOUT_MS;
  let lastDump = "";
  while (Date.now() < deadline) {
    const state = await page.evaluate(() => ({ ...window.__agentTownSpike }));
    const consoleJoined = consoleHits.join("\n");
    const consoleSse =
      /SSE:\s*connected|SSE connected|status.*connected/i.test(consoleJoined) ||
      consoleHits.some((l) => /sim\.tick_/i.test(l));
    const sawSim = (state.eventTypes || []).some(
      (t) => String(t).includes("sim.") || String(t).includes("tick"),
    );
    const dump = JSON.stringify({
      sseOpen: state.sseOpen,
      sseHttpOk: state.sseHttpOk,
      events: (state.eventTypes || []).slice(0, 8),
      errors: (state.errors || []).slice(0, 3),
      consoleSse,
    });
    if (dump !== lastDump) {
      console.log("probe", dump);
      lastDump = dump;
    }

    // Strict §14.6: HTTP OK + at least one sim/tick frame (or console evidence).
    if (state.sseHttpOk && (sawSim || consoleSse)) {
      console.log("OK jslib SSE smoke", (state.eventTypes || []).slice(0, 5).join(",") || "connected");
      await browser.close();
      process.exit(0);
    }
    // Soft pass only when explicitly opted in (legacy CI / CORS-only probe).
    if (
      ALLOW_CONNECTED_ONLY &&
      state.sseHttpOk &&
      Date.now() - t0 > 45_000 &&
      (state.eventTypes || []).length === 0
    ) {
      console.log("OK jslib SSE connected (SPIKE_ALLOW_CONNECTED_ONLY — no sim.* frame)");
      await browser.close();
      process.exit(0);
    }

    // Fail fast: Unity threw before jslib opened SSE (typical: stripped shader → Material null).
    if (!state.sseOpen && fatalHints.length > 0 && Date.now() - t0 > 25_000) {
      await browser.close();
      fail(
        `Unity WebGL boot error before SSE (rebuild after shader fallback fix): ${fatalHints[0]}`,
      );
    }

    await new Promise((r) => setTimeout(r, 1000));
  }

  const finalState = await page.evaluate(() => ({ ...window.__agentTownSpike }));
  await browser.close();
  const hint =
    fatalHints.length > 0
      ? ` bootError=${fatalHints[0]}`
      : " — if canvas loaded but no SSE, rebuild WebGL after latest TownBootstrap/TownBuilder shader fallbacks";
  fail(
    `timeout ${TIMEOUT_MS}ms — sseOpen=${finalState.sseOpen} httpOk=${finalState.sseHttpOk} events=${(finalState.eventTypes || []).join(",") || "-"} errors=${(finalState.errors || []).join(";") || "-"}${hint}`,
  );
}

main().catch((e) => fail(String(e?.stack || e)));
