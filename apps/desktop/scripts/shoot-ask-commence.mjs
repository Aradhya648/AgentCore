// Screenshot harness for 开工提案 layout preview (#/preview/ask-commence).
//
// Companion to shoot.mjs / shoot-whiteboard.mjs: boots the offline web entry and
// deep-links each ask-commence layout variant for product A/B eyeballing.
//
// Usage:
//   node scripts/shoot-ask-commence.mjs
//   node scripts/shoot-ask-commence.mjs v2
//   pnpm -C apps/desktop shoot:ask-commence

import { mkdir, readFile, rm } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { createServer } from "vite";

const here = dirname(fileURLToPath(import.meta.url));
const desktopDir = resolve(here, "..");
const scenesPath = resolve(
  desktopDir,
  "src/renderer/preview/askCommenceScenes.ts",
);
const SHOOT_OUT_DIR = "shoot-out-ask-commence";
const outDir = resolve(desktopDir, SHOOT_OUT_DIR);

const SETTLE_MS = Number(process.env.SHOOT_SETTLE_MS ?? 900);
const VIEWPORT = {
  width: Number(process.env.SHOOT_WIDTH ?? 1440),
  height: Number(process.env.SHOOT_HEIGHT ?? 900),
};
const SCALE = Number(process.env.SHOOT_SCALE ?? 2);
const THEME = process.env.SHOOT_THEME === "dark" ? "dark" : "light";
const filter = (process.argv[2] ?? "").toLowerCase();

async function loadSceneIds() {
  const src = await readFile(scenesPath, "utf8");
  const ids = [];
  const re = /id:\s*"(ask-commence-v\d+)"/g;
  let m = re.exec(src);
  while (m !== null) {
    if (!ids.includes(m[1])) ids.push(m[1]);
    m = re.exec(src);
  }
  return ids;
}

async function main() {
  process.chdir(desktopDir);

  let ids = await loadSceneIds();
  if (filter) ids = ids.filter((id) => id.toLowerCase().includes(filter));
  if (ids.length === 0) {
    console.error(
      filter
        ? `No ask-commence scenes matched filter "${filter}".`
        : `No scene ids found in ${scenesPath}.`,
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
  for (const [i, id] of ids.entries()) {
    const file = `${id}.png`;
    const label = `[${i + 1}/${ids.length}] ${file}`;
    pageErrors.length = 0;
    let failure = null;
    try {
      const url = new URL("index.web.html", base);
      url.searchParams.set("shoot-ask-commence", String(i));
      url.hash = `/preview/ask-commence?s=${encodeURIComponent(id)}`;
      await page.goto(url.href, { waitUntil: "load", timeout: 30_000 });
      await page.waitForSelector(`[data-preview-ask-commence="${id}"]`, {
        timeout: 15_000,
      });
      await page.waitForSelector(`[data-ask-commence-variant="${id}"]`, {
        timeout: 10_000,
      });
      await page.evaluate(() => document.fonts?.ready).catch(() => {});
      await page.waitForTimeout(SETTLE_MS);
    } catch (err) {
      failure = String(err?.message ?? err);
    }
    await page.screenshot({ path: resolve(outDir, file) }).catch(() => {});
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

  console.log(`\nDone: ${ok}/${ids.length} → ${outDir}`);
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
