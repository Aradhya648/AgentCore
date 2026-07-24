#!/usr/bin/env node
/**
 * Reusable headless screenshot helper for the mobile web app (visual review).
 *
 * Usage:
 *   pnpm -C apps/mobile shot <url> [outFile] [WIDTHxHEIGHT]
 *   node apps/mobile/scripts/shot.cjs http://localhost:5175/preview?s=single_agent_tool out.png 390x844
 *
 * Defaults: url=http://localhost:5175/, viewport="iPhone 13",
 *           out=apps/mobile/.shots/<timestamp>.png (dir is gitignored).
 *
 * Browser: mobile intentionally has no playwright dep, so we resolve playwright
 * from apps/desktop. If the exact Chromium build playwright expects is missing,
 * we fall back to any chromium-* already in the ms-playwright cache — so a
 * playwright version bump doesn't force a re-download. Override with PW_EXE.
 */
const fs = require("fs");
const os = require("os");
const path = require("path");

const pwPath = require.resolve("playwright", {
  paths: [path.join(__dirname, "..", "..", "desktop", "node_modules")],
});
const { chromium, devices } = require(pwPath);

function cacheDir() {
  if (process.platform === "win32")
    return path.join(os.homedir(), "AppData", "Local", "ms-playwright");
  if (process.platform === "darwin")
    return path.join(os.homedir(), "Library", "Caches", "ms-playwright");
  return path.join(os.homedir(), ".cache", "ms-playwright");
}

function findCachedChromium() {
  if (process.env.PW_EXE) return process.env.PW_EXE;
  const cache = cacheDir();
  if (!fs.existsSync(cache)) return null;
  const dirs = fs
    .readdirSync(cache)
    .filter((d) => d.startsWith("chromium-"))
    .sort()
    .reverse(); // newest build first
  const rels = [
    ["chrome-win64", "chrome.exe"],
    ["chrome-win", "chrome.exe"],
    ["chrome-mac", "Chromium.app", "Contents", "MacOS", "Chromium"],
    ["chrome-linux", "chrome"],
  ];
  for (const d of dirs)
    for (const rel of rels) {
      const exe = path.join(cache, d, ...rel);
      if (fs.existsSync(exe)) return exe;
    }
  return null;
}

async function launchChromium() {
  try {
    return await chromium.launch();
  } catch (err) {
    const exe = findCachedChromium();
    if (!exe) throw err;
    return await chromium.launch({ executablePath: exe });
  }
}

(async () => {
  const url = process.argv[2] || "http://localhost:5175/";
  const outArg = process.argv[3];
  const sizeArg = process.argv[4];

  const outDir = path.join(__dirname, "..", ".shots");
  fs.mkdirSync(outDir, { recursive: true });
  const out =
    outArg ||
    path.join(outDir, `${new Date().toISOString().replace(/[:.]/g, "-")}.png`);

  let ctxOpts = { ...devices["iPhone 13"] };
  if (sizeArg && /^\d+x\d+$/.test(sizeArg)) {
    const [w, h] = sizeArg.split("x").map(Number);
    ctxOpts = {
      viewport: { width: w, height: h },
      deviceScaleFactor: 2,
      isMobile: true,
    };
  }

  const browser = await launchChromium();
  const ctx = await browser.newContext(ctxOpts);
  const page = await ctx.newPage();
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 20000 });
  await page.waitForTimeout(2500); // let React render + auth bootstrap settle
  await page.screenshot({ path: out, fullPage: true });
  console.log(`OK url=${page.url()} -> ${out}`);
  await browser.close();
})().catch((e) => {
  console.error(`SHOT_ERR ${e.message}`);
  process.exit(1);
});
