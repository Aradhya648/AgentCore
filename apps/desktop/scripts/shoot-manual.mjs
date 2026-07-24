// Screenshot harness for static product-manual pages (four chapters).
//
// The SSE conformance preview (`scripts/shoot.mjs` → `#/preview`) replays AI event
// vectors only — it cannot render static routes. This companion script boots the same
// offline web entry (vite.web.config.ts → main.web.tsx) and deep-links manual routes
// declared in src/renderer/preview/manual-scenes.json.
//
// Wait strategy for real graphs / lazy embeds:
//   1. data-preview-manual + section marker
//   2. scroll section into view (instant)
//   3. data-manual-embed keys (Suspense resolved = no .animate-pulse)
//   4. for HeroGraph / MechanismScenarios: data-elk-ready="true" (ELK layout done)
//
// Usage:
//   node scripts/shoot-manual.mjs
//   node scripts/shoot-manual.mjs faq          # filter by scene id substring
//   SHOOT_SETTLE_MS=1200 node scripts/shoot-manual.mjs

import { mkdir, readFile, rm, stat } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { createServer } from "vite";

const here = dirname(fileURLToPath(import.meta.url));
const desktopDir = resolve(here, "..");
const scenesPath = resolve(
  desktopDir,
  "src/renderer/preview/manual-scenes.json",
);
const SHOOT_OUT_DIR = "shoot-out-manual";
const outDir = resolve(desktopDir, SHOOT_OUT_DIR);

const SETTLE_MS = Number(process.env.SHOOT_SETTLE_MS ?? 1200);
const VIEWPORT = {
  width: Number(process.env.SHOOT_WIDTH ?? 1440),
  height: Number(process.env.SHOOT_HEIGHT ?? 900),
};
const SCALE = Number(process.env.SHOOT_SCALE ?? 2);
const THEME = process.env.SHOOT_THEME === "dark" ? "dark" : "light";
const filter = (process.argv[2] ?? "").toLowerCase();

/** Min PNG size (bytes) — below this is treated as blank / failed capture. */
const MIN_PNG_BYTES = 8_000;

/** Embed keys that wrap real ELK + React Flow canvases. */
const ELK_EMBED_KEYS = new Set(["HeroGraph", "MechanismScenarios"]);

async function loadScenes() {
  const scenes = JSON.parse(await readFile(scenesPath, "utf8"));
  if (!Array.isArray(scenes))
    throw new Error("manual-scenes.json must be an array");
  return scenes.filter((s) => s?.id && s?.path);
}

function hashFor(scene) {
  const base = scene.path.startsWith("/") ? scene.path : `/${scene.path}`;
  if (scene.section) return `${base}?s=${encodeURIComponent(scene.section)}`;
  return base;
}

function previewManualFor(scene) {
  if (scene.previewManual) return scene.previewManual;
  // Derive from path: /toolbox/manual/reference → manual-reference
  const m = String(scene.path).match(/\/toolbox\/manual\/([^/?#]+)/);
  return m ? `manual-${m[1]}` : "manual-reference";
}

async function waitForEmbedReady(page, key) {
  await page.waitForSelector(`[data-manual-embed="${key}"]`, {
    timeout: 20_000,
  });
  // Lazy chunk + Suspense: wait until pulse fallback is gone inside the embed.
  await page.waitForFunction(
    (embedKey) => {
      const root = document.querySelector(`[data-manual-embed="${embedKey}"]`);
      if (!root) return false;
      return !root.querySelector(".animate-pulse");
    },
    key,
    { timeout: 20_000 },
  );
  // Scroll embed into view so LazyMount (non-shoot) / layout measure can run.
  await page.evaluate((embedKey) => {
    document
      .querySelector(`[data-manual-embed="${embedKey}"]`)
      ?.scrollIntoView({ behavior: "instant", block: "center" });
  }, key);
  if (!ELK_EMBED_KEYS.has(key)) return;
  // ELK async layout: EmbeddedGraphCanvas sets data-elk-ready when layout+width ready.
  await page.waitForSelector(
    `[data-manual-embed="${key}"] [data-elk-ready="true"]`,
    { timeout: 25_000 },
  );
  await page
    .waitForSelector(`[data-manual-embed="${key}"] .react-flow`, {
      timeout: 10_000,
    })
    .catch(() => {});
}

async function main() {
  process.chdir(desktopDir);

  let scenes = await loadScenes();
  if (filter) {
    scenes = scenes.filter((s) => s.id.toLowerCase().includes(filter));
  }
  if (scenes.length === 0) {
    console.error(
      filter
        ? `No manual scenes matched filter "${filter}".`
        : `No scenes in ${scenesPath}.`,
    );
    process.exitCode = 1;
    return;
  }

  await rm(outDir, { recursive: true, force: true });
  await mkdir(outDir, { recursive: true });

  console.log("Booting web preview (vite.web.config.ts)…");
  const server = await createServer({
    configFile: resolve(desktopDir, "vite.web.config.ts"),
    logLevel: "warn",
  });
  await server.listen();
  const base = server.resolvedUrls?.local?.[0];
  if (!base) {
    await server.close();
    throw new Error("Vite did not report a local URL.");
  }

  let browser;
  try {
    browser = await chromium.launch();
  } catch (err) {
    await server.close();
    console.error(
      `Failed to launch Chromium. Install once:\n  pnpm -C apps/desktop exec playwright install chromium\n${String(err?.message ?? err)}`,
    );
    process.exitCode = 1;
    return;
  }

  const page = await browser.newPage({
    viewport: VIEWPORT,
    deviceScaleFactor: SCALE,
    colorScheme: THEME,
  });
  await page.addInitScript((theme) => {
    try {
      localStorage.setItem("agentcore:theme", theme);
    } catch {
      /* ignore */
    }
  }, THEME);

  const pageErrors = [];
  page.on("pageerror", (err) => pageErrors.push(err.message));

  let ok = 0;
  const failures = [];
  for (const [i, scene] of scenes.entries()) {
    const file = `${scene.id}.png`;
    const outPath = resolve(outDir, file);
    const label = `[${i + 1}/${scenes.length}] ${file}`;
    pageErrors.length = 0;
    let failure = null;
    const section = scene.section ?? "top";
    const previewManual = previewManualFor(scene);
    try {
      const url = new URL("index.web.html", base);
      url.searchParams.set("shoot-manual", String(i));
      url.hash = hashFor(scene);
      await page.goto(url.href, { waitUntil: "load", timeout: 30_000 });
      await page.waitForSelector(
        `[data-preview-manual="${previewManual}"][data-preview-section="${section}"]`,
        { timeout: 15_000 },
      );
      // Scroll section first so LazyMount / section-relative embeds can mount.
      if (scene.section) {
        await page.evaluate((id) => {
          document
            .getElementById(id)
            ?.scrollIntoView({ behavior: "instant", block: "start" });
        }, scene.section);
      }
      const embeds = Array.isArray(scene.waitEmbeds) ? scene.waitEmbeds : [];
      for (const key of embeds) {
        await waitForEmbedReady(page, key);
      }
      // Frame: prefer first waited embed (cards/graphs) over section heading.
      if (embeds.length > 0) {
        await page.evaluate((embedKey) => {
          document
            .querySelector(`[data-manual-embed="${embedKey}"]`)
            ?.scrollIntoView({ behavior: "instant", block: "start" });
        }, embeds[0]);
      } else if (scene.section) {
        await page.evaluate((id) => {
          document
            .getElementById(id)
            ?.scrollIntoView({ behavior: "instant", block: "start" });
        }, scene.section);
      }
      await page.evaluate(() => document.fonts?.ready).catch(() => {});
      await page.waitForTimeout(SETTLE_MS);
      const crashed = await page
        .locator("text=出了点问题")
        .count()
        .catch(() => 0);
      if (crashed > 0) {
        failure = "route error boundary visible (出了点问题)";
      }
    } catch (err) {
      failure = String(err?.message ?? err);
    }
    await page.screenshot({ path: outPath }).catch(() => {});
    try {
      const st = await stat(outPath);
      if (st.size < MIN_PNG_BYTES) {
        failure = `${failure ? `${failure}; ` : ""}screenshot too small (${st.size}B < ${MIN_PNG_BYTES}B) — likely blank`;
      }
    } catch {
      failure = `${failure ? `${failure}; ` : ""}screenshot missing`;
    }
    if (pageErrors.length) {
      failure = `${failure ? `${failure}; ` : ""}page error: ${pageErrors.join(" | ")}`;
    }
    if (failure) {
      failures.push({ name: file, error: failure });
      console.error(`  ✗ ${label} — ${failure}`);
    } else {
      ok += 1;
      console.log(`  ✓ ${label}`);
    }
  }

  await browser.close();
  await server.close();

  console.log(`\nDone: ${ok}/${scenes.length} → ${outDir}`);
  if (failures.length) {
    console.error(`${failures.length} failed:`);
    for (const f of failures) console.error(`  - ${f.name}: ${f.error}`);
    process.exitCode = 1;
  }
}

main().catch((err) => {
  console.error(err);
  process.exitCode = 1;
});
