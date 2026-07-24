/**
 * AgentTown WebGL Offline Demo screenshots (no backend / LLM).
 *
 * Serves Builds/WebGL, opens ?demo=1&shoot=1&pack=… for each story pack (plus the
 * ?episode=3&shoot=1 programme-mode Playback face), waits until the Offline build is
 * ready on a landmark tick, then writes PNGs under apps/town/shoot-out/.
 *
 * Usage (repo root):
 *   pnpm town:shoot:webgl
 *   node apps/town/scripts/shoot-webgl-demo.mjs
 *
 * Requires:
 *   - WebGL build at apps/town/Builds/WebGL/index.html  → pnpm town:build:webgl
 *   - Playwright Chromium (apps/desktop or hoisted)     → pnpm -C apps/desktop exec playwright install chromium
 *
 * Env:
 *   SHOOT_PORT          static server port (default 4179)
 *   SHOOT_TIMEOUT_MS    per-pack boot wait (default 120000)
 *   SHOOT_SETTLE_MS     post-interaction settle before PNG (default 4500)
 *   SHOOT_PLAYWRIGHT    optional absolute path to playwright package root
 */

import { createRequire } from "node:module";
import { createServer } from "node:http";
import { dirname, resolve, join } from "node:path";
import { fileURLToPath } from "node:url";
import { existsSync, createReadStream, mkdirSync, rmSync, statSync } from "node:fs";

const here = dirname(fileURLToPath(import.meta.url));
const townRoot = resolve(here, "..");
const webglDir = resolve(townRoot, "Builds/WebGL");
const webglIndex = join(webglDir, "index.html");
const outDir = resolve(townRoot, "shoot-out");

/**
 * Shoot scenes: three Offline story packs + the programme-mode Playback face.
 * Landmark ticks stay in sync with DemoPackIds.ShootLandmarkTick and
 * TownBootstrap.ShowShootLandmarkTick.
 */
const SCENES = [
  { id: "price_surge", search: "?demo=1&shoot=1&pack=price_surge", tick: 9 },
  { id: "festival", search: "?demo=1&shoot=1&pack=festival", tick: 12 },
  { id: "town_hall", search: "?demo=1&shoot=1&pack=town_hall", tick: 6 },
  // 恋综节目模式（离线第 3 期）— 白天市集 landmark（caption + follow_pair 镜头）
  { id: "episode_3", search: "?episode=3&shoot=1", tick: 24 },
];
const PORT = Number(process.env.SHOOT_PORT || 4179);
const TIMEOUT_MS = Number(process.env.SHOOT_TIMEOUT_MS || 120_000);
const SETTLE_MS = Number(process.env.SHOOT_SETTLE_MS || 6_500);
const VIEWPORT = {
  width: Number(process.env.SHOOT_WIDTH || 1440),
  height: Number(process.env.SHOOT_HEIGHT || 900),
};

function fail(msg) {
  console.error("FAIL", msg);
  process.exit(1);
}

async function loadChromium() {
  const requirePaths = [];
  if (process.env.SHOOT_PLAYWRIGHT) {
    requirePaths.push(resolve(process.env.SHOOT_PLAYWRIGHT, "package.json"));
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

  try {
    const mod = await import("playwright");
    if (mod?.chromium) return mod.chromium;
  } catch {
    /* */
  }

  throw new Error(
    "playwright not found. Install once:\n" +
      "  pnpm -C apps/desktop exec playwright install chromium\n" +
      "Or: npx --yes -p playwright playwright install chromium",
  );
}

const MIME = {
  ".html": "text/html; charset=utf-8",
  ".js": "application/javascript",
  ".wasm": "application/wasm",
  ".json": "application/json",
  ".data": "application/octet-stream",
  ".css": "text/css",
  ".png": "image/png",
  ".jpg": "image/jpeg",
  ".ico": "image/x-icon",
  ".unityweb": "application/octet-stream",
};

/** Unity gzip builds need Content-Encoding so the browser decompresses before the loader parses. */
function responseHeaders(filePath) {
  const lower = filePath.toLowerCase();
  const headers = {
    "Cache-Control": "no-cache",
    "Access-Control-Allow-Origin": "*",
  };
  if (lower.endsWith(".gz")) {
    const withoutGz = lower.slice(0, -3);
    headers["Content-Encoding"] = "gzip";
    headers["Content-Type"] = contentType(withoutGz);
    return headers;
  }
  if (lower.endsWith(".br")) {
    const withoutBr = lower.slice(0, -3);
    headers["Content-Encoding"] = "br";
    headers["Content-Type"] = contentType(withoutBr);
    return headers;
  }
  headers["Content-Type"] = contentType(lower);
  return headers;
}

function contentType(filePath) {
  const lower = filePath.toLowerCase();
  for (const [ext, type] of Object.entries(MIME)) {
    if (lower.endsWith(ext)) return type;
  }
  return "application/octet-stream";
}

function startStaticServer(root, port) {
  return new Promise((resolveServer, reject) => {
    const server = createServer((req, res) => {
      try {
        const url = new URL(req.url || "/", `http://127.0.0.1:${port}`);
        let rel = decodeURIComponent(url.pathname);
        if (rel === "/") rel = "/index.html";
        const filePath = resolve(root, "." + rel);
        if (!filePath.startsWith(root) || !existsSync(filePath) || statSync(filePath).isDirectory()) {
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
    server.once("error", reject);
    server.listen(port, "127.0.0.1", () => resolveServer(server));
  });
}

async function ensureHost(preferredPort) {
  const candidates = [preferredPort, preferredPort + 1, preferredPort + 2, 4190, 4191];
  let lastErr;
  for (const port of candidates) {
    try {
      const server = await startStaticServer(webglDir, port);
      return {
        baseUrl: `http://127.0.0.1:${port}`,
        close: () =>
          new Promise((r) => {
            server.close(() => r());
          }),
      };
    } catch (e) {
      lastErr = e;
      if (e?.code === "EADDRINUSE") {
        console.warn(`port ${port} busy — trying next`);
        continue;
      }
      throw e;
    }
  }
  throw lastErr || new Error(`No free port among ${candidates.join(", ")}`);
}

async function waitOfflineReady(page, packId, timeoutMs) {
  const deadline = Date.now() + timeoutMs;
  let lastHint = "waiting for canvas";
  const t0 = Date.now();
  // Older WebGL builds lack AgentTownDemo.jslib — fall back after canvas + loading bar hide.
  const FALLBACK_MIN_MS = Number(process.env.SHOOT_FALLBACK_MIN_MS || 18_000);

  await page.waitForSelector("#unity-canvas, canvas", {
    timeout: Math.min(60_000, timeoutMs),
  }).catch(() => {
    lastHint = "canvas not found yet";
  });

  while (Date.now() < deadline) {
    // Prefer jslib flag (UI Toolkit labels are not in the DOM on WebGL).
    const probe = await page.evaluate((expectedPack) => {
      const canvas = document.querySelector("#unity-canvas") || document.querySelector("canvas");
      const demo = window.__agentTownDemo;
      const loadingBar = document.querySelector("#unity-loading-bar");
      const loadingHidden =
        !loadingBar ||
        loadingBar.style.display === "none" ||
        getComputedStyle(loadingBar).display === "none";
      const bridgeReady =
        !!demo &&
        demo.ready === true &&
        demo.offline === true &&
        (!expectedPack || demo.packId === expectedPack);
      return {
        hasCanvas: !!canvas,
        bridgeReady,
        loadingHidden,
        demo: demo
          ? {
              packId: demo.packId,
              displayName: demo.displayName,
              offline: demo.offline,
              tick: demo.tick,
              shoot: demo.shoot,
            }
          : null,
      };
    }, packId);

    lastHint = JSON.stringify(probe);
    if (probe.hasCanvas && probe.bridgeReady) {
      return { ...probe, via: "bridge" };
    }

    // Fallback for builds before AgentTownDemo.jslib: canvas + loader gone + settle.
    if (
      probe.hasCanvas &&
      probe.loadingHidden &&
      Date.now() - t0 >= FALLBACK_MIN_MS
    ) {
      console.warn(
        `  note: __agentTownDemo missing — using canvas/loader fallback (rebuild for pack-aware ready: pnpm town:build:webgl)`,
      );
      return { ...probe, via: "fallback" };
    }

    await new Promise((r) => setTimeout(r, 1000));
  }

  throw new Error(
    `Offline Demo not ready for pack=${packId} within ${timeoutMs}ms — last=${lastHint}. ` +
      "If boot is slow, raise SHOOT_TIMEOUT_MS. Shader/boot crash → pnpm town:build:webgl",
  );
}

/**
 * Wait until the playhead reaches the scene landmark tick
 * (bubbles / trade / banner / show caption). Shoot mode seeks there on boot;
 * this covers older builds that only autoplay from tick 3.
 */
async function waitInteractionTick(page, targetTick, timeoutMs) {
  const target = targetTick ?? 9;
  const deadline = Date.now() + timeoutMs;
  let lastHint = `waiting for tick>=${target}`;

  while (Date.now() < deadline) {
    const probe = await page.evaluate((minTick) => {
      const demo = window.__agentTownDemo;
      const tick = typeof demo?.tick === "number" ? demo.tick : 0;
      return {
        tick,
        ready: !!demo?.ready,
        shoot: !!demo?.shoot,
        ok: tick >= minTick,
      };
    }, target);

    lastHint = JSON.stringify(probe);
    if (probe.ok) {
      return { ...probe, target, via: "tick" };
    }

    // Pre-tick bridge builds: cannot observe playhead — wait a playback window.
    if (probe.ready && probe.tick === 0 && Date.now() + 1000 >= deadline) {
      break;
    }

    await new Promise((r) => setTimeout(r, 500));
  }

  // Grace path: older builds without SetTick — extra settle so autoplay can advance.
  const legacyWait = Number(process.env.SHOOT_LEGACY_TICK_WAIT_MS || 8_000);
  console.warn(
    `  note: tick probe did not reach ${target} (last=${lastHint}) — waiting ${legacyWait}ms for autoplay`,
  );
  await new Promise((r) => setTimeout(r, legacyWait));
  return { target, via: "legacy-wait", tick: 0 };
}

async function main() {
  if (!existsSync(webglIndex)) {
    fail(
      `WebGL build missing: ${webglIndex}\n` +
        "Run first: pnpm town:build:webgl",
    );
  }

  let chromium;
  try {
    chromium = await loadChromium();
  } catch (e) {
    fail(String(e?.message || e));
  }

  rmSync(outDir, { recursive: true, force: true });
  mkdirSync(outDir, { recursive: true });

  let host;
  try {
    host = await ensureHost(PORT);
  } catch (e) {
    fail(
      `Could not bind static server on :${PORT}: ${e?.message || e}\n` +
        "Set SHOOT_PORT to a free port, or stop the process using it.",
    );
  }

  console.log("Serving", webglDir, "→", host.baseUrl);

  let browser;
  try {
    // Prefer GPU WebGL — SwiftShader often caps Offline Demo around ~20 FPS in headless.
    browser = await chromium.launch({
      headless: true,
      args: [
        "--ignore-gpu-blocklist",
        "--enable-webgl",
        "--use-gl=angle",
        "--use-angle=d3d11",
      ],
    });
  } catch (e) {
    await host.close();
    fail(
      `Failed to launch Chromium.\n` +
        `Install once: pnpm -C apps/desktop exec playwright install chromium\n` +
        String(e?.message || e),
    );
  }

  const page = await browser.newPage({ viewport: VIEWPORT });
  const pageErrors = [];
  page.on("pageerror", (err) => pageErrors.push(String(err?.message || err)));
  page.on("console", (msg) => {
    if (msg.type() === "error") {
      console.log(`[console.error]`, msg.text().slice(0, 200));
    }
  });

  const failures = [];
  try {
    for (const [i, scene] of SCENES.entries()) {
      const url = `${host.baseUrl}/${scene.search}`;
      const outFile = join(outDir, `${scene.id}.png`);
      console.log(`[${i + 1}/${SCENES.length}] ${scene.id} → ${url}`);
      pageErrors.length = 0;
      try {
        await page.goto(url, {
          waitUntil: "domcontentloaded",
          timeout: Math.min(90_000, TIMEOUT_MS),
        });
        const ready = await waitOfflineReady(page, scene.id, TIMEOUT_MS);
        console.log(
          `  ready via=${ready.via} tick=${ready.demo?.tick ?? "?"} shoot=${ready.demo?.shoot ?? "?"}`,
        );
        const ix = await waitInteractionTick(page, scene.tick, Math.min(45_000, TIMEOUT_MS));
        console.log(`  interaction via=${ix.via} tick=${ix.tick ?? "?"} target=${ix.target}`);
        await new Promise((r) => setTimeout(r, SETTLE_MS));
        await page.screenshot({ path: outFile, fullPage: false });
        if (!existsSync(outFile)) {
          throw new Error("screenshot file not written");
        }
        console.log("  OK", outFile);
      } catch (e) {
        const detail = String(e?.message || e);
        const bootErr = pageErrors[0] ? ` pageerror=${pageErrors[0].slice(0, 160)}` : "";
        console.error("  FAIL", detail + bootErr);
        failures.push(`${scene.id}: ${detail}`);
      }
    }
  } finally {
    await browser.close().catch(() => {});
    await host.close().catch(() => {});
  }

  if (failures.length > 0) {
    fail(
      `${failures.length}/${SCENES.length} scene screenshot(s) failed:\n  - ${failures.join("\n  - ")}\n` +
        "If Unity boot is slow, raise SHOOT_TIMEOUT_MS / SHOOT_SETTLE_MS. " +
        "If shaders crash, rebuild: pnpm town:build:webgl",
    );
  }

  console.log(`OK wrote ${SCENES.length} PNGs → ${outDir}`);
}

main().catch((e) => fail(String(e?.stack || e)));
