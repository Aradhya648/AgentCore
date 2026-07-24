// Screenshot harness for the self-built whiteboard canvas preview (#/preview/whiteboard).
//
// The SSE conformance preview (`scripts/shoot.mjs` → `#/preview`) replays AI event vectors into
// the chat surface only. The whiteboard is a separate canvas whose "vector" is a SCENE, so this
// companion script (mirroring shoot-manual.mjs) boots the same offline web entry
// (vite.web.config.ts → main.web.tsx) and deep-links each committed whiteboard scene, writing a
// PNG per scene. It doubles as a render smoke gate: a scene that crashes on render (uncaught
// error, or the page never mounts) fails the process non-zero.
//
// Scene ids come from src/renderer/preview/whiteboardScenes.ts. This harness reads the same list
// via a tiny transform of that module so it can't drift from the app.
//
// Usage:
//   node scripts/shoot-whiteboard.mjs               # every whiteboard scene
//   node scripts/shoot-whiteboard.mjs rotation      # filter by scene id substring
//   SHOOT_SETTLE_MS=1200 node scripts/shoot-whiteboard.mjs
//
// Env knobs: SHOOT_SETTLE_MS (default 900), SHOOT_WIDTH (1440), SHOOT_HEIGHT (900),
// SHOOT_SCALE (2), SHOOT_THEME ("light" | "dark", default light).

import { mkdir, readFile, rm } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { createServer } from "vite";

const here = dirname(fileURLToPath(import.meta.url));
const desktopDir = resolve(here, "..");
const scenesPath = resolve(
  desktopDir,
  "src/renderer/preview/whiteboardScenes.ts",
);
const SHOOT_OUT_DIR = "shoot-out-whiteboard";
const outDir = resolve(desktopDir, SHOOT_OUT_DIR);

const SETTLE_MS = Number(process.env.SHOOT_SETTLE_MS ?? 900);
const VIEWPORT = {
  width: Number(process.env.SHOOT_WIDTH ?? 1440),
  height: Number(process.env.SHOOT_HEIGHT ?? 900),
};
const SCALE = Number(process.env.SHOOT_SCALE ?? 2);
const THEME = process.env.SHOOT_THEME === "dark" ? "dark" : "light";
const filter = (process.argv[2] ?? "").toLowerCase();

/** Extract scene ids from the source module by matching the `id:` field of each scene object.
 * The scenes are code-authored (not JSON), so this scans the source rather than importing TS. */
async function loadSceneIds() {
  const src = await readFile(scenesPath, "utf8");
  const ids = [];
  const re = /id:\s*"(board_[a-z0-9_]+)"/g;
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
        ? `No whiteboard scenes matched filter "${filter}".`
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
      url.searchParams.set("shoot-whiteboard", String(i));
      url.hash = `/preview/whiteboard?s=${encodeURIComponent(id)}`;
      await page.goto(url.href, { waitUntil: "load", timeout: 30_000 });
      await page.waitForSelector(`[data-preview-board="${id}"]`, {
        timeout: 15_000,
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
      console.error(`  \u2717 ${label} — ${failure}`);
    } else {
      ok += 1;
      console.log(`  \u2713 ${label}`);
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
