// Screenshot harness for 能力包纯展示 preview (#/preview/capability-packs).
//
// Usage:
//   node scripts/shoot-capability-packs.mjs
//   pnpm -C apps/desktop shoot:capability-packs

import { mkdir, readFile, rm } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { createServer } from "vite";

const here = dirname(fileURLToPath(import.meta.url));
const desktopDir = resolve(here, "..");
const scenesPath = resolve(
  desktopDir,
  "src/renderer/preview/capabilityPackScenes.ts",
);
const SHOOT_OUT_DIR = "shoot-out-capability-packs";
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
  const re = /id:\s*"(pack-[^"]+)"/g;
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
        ? `No capability-pack scenes matched filter "${filter}".`
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
      localStorage.setItem("agentcore:theme", JSON.stringify(theme));
    } catch {
      /* ignore */
    }
  }, THEME);

  // Soft-stub ambient shell REST so Sidebar/messaging never crash the preview.
  await page.route("**/v1/**", async (route) => {
    const url = route.request().url();
    if (url.includes("/v1/messaging") || url.includes("/chats")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ chats: [], data: [] }),
      });
      return;
    }
    if (url.includes("/conversations") || url.includes("/folders")) {
      await route.fulfill({
        status: 200,
        contentType: "application/json",
        body: JSON.stringify({ conversations: [], folders: [], data: [] }),
      });
      return;
    }
    await route.fulfill({
      status: 200,
      contentType: "application/json",
      body: "{}",
    });
  });

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
      url.searchParams.set("shoot-packs", String(i));
      url.hash = `/preview/capability-packs?s=${encodeURIComponent(id)}`;
      await page.goto(url.href, { waitUntil: "load", timeout: 30_000 });
      await page.waitForSelector(`[data-preview-capability-packs="${id}"]`, {
        timeout: 15_000,
      });
      await page.waitForSelector('[data-testid="capability-packs"]', {
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
