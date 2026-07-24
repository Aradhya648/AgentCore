/**
 * 内部自检截图：把 /preview/maps 的两版竖图截下来供 review。
 * 复用 apps/desktop 已安装的 playwright，连现有 :3000 dev server。
 *
 *   node scripts/shot-preview.mjs            # 默认连 http://localhost:3000
 *   PREVIEW_PORT=3100 node scripts/shot-preview.mjs
 *
 * 产物写到 apps/website/.shots/（已 gitignore 范畴外，自检用，可随时删）。
 */
import { createRequire } from "node:module";
import { mkdir } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";

const require = createRequire("C:/Project/AgentCore/apps/desktop/package.json");
const { chromium } = require("playwright");

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.resolve(__dirname, "..");
const OUT_DIR = path.join(ROOT, ".shots");
const PORT = process.env.PREVIEW_PORT || "3000";
const URL = `http://127.0.0.1:${PORT}/preview/maps`;

async function main() {
  await mkdir(OUT_DIR, { recursive: true });
  const browser = await chromium.launch({ args: ["--no-proxy-server"] });
  try {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 1200 },
      deviceScaleFactor: 1.5,
    });
    console.log(`→ goto ${URL}`);
    await page.goto(URL, { waitUntil: "load", timeout: 180_000 });
    await page.waitForSelector('svg[role="img"]', { timeout: 45_000 });
    await page.waitForTimeout(1500);

    const full = path.join(OUT_DIR, "_full_page.png");
    await page.screenshot({ path: full, fullPage: true });
    console.log(`  ✓ ${path.relative(ROOT, full)}`);

    const svgs = page.locator('svg[role="img"]');
    const count = await svgs.count();
    console.log(`→ found ${count} diagrams`);
    if (count >= 1) {
      const a = path.join(OUT_DIR, "_a_simple.png");
      await svgs.nth(0).screenshot({ path: a });
      console.log(`  ✓ ${path.relative(ROOT, a)}`);
    }
    if (count >= 2) {
      const b = path.join(OUT_DIR, "_b_full.png");
      await svgs.nth(1).screenshot({ path: b });
      console.log(`  ✓ ${path.relative(ROOT, b)}`);
    }
    console.log("done");
  } finally {
    await browser.close();
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
