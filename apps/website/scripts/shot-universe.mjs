/**
 * /preview/universe 无头截图自检：逐章节（?s=0..6&snap=1）各截一张。
 * 复用 apps/desktop 已安装的 playwright；WebGL 走 SwiftShader 软渲染。
 *
 *   node scripts/shot-universe.mjs                 # 默认连 http://localhost:3213
 *   PREVIEW_PORT=3000 node scripts/shot-universe.mjs
 *
 * 产物写到 apps/website/.shots/universe_s*.png（自检用，可随时删）。
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
const PORT = process.env.PREVIEW_PORT || "3213";
// 注意用 localhost：Next 16 dev 会拦截 127.0.0.1 发来的跨域资源请求。
const BASE = `http://localhost:${PORT}/preview/universe/`;
const SECTIONS = 7;

const MOBILE = process.env.MOBILE === "1";

async function main() {
  await mkdir(OUT_DIR, { recursive: true });
  const browser = await chromium.launch({
    args: [
      "--no-proxy-server",
      "--enable-unsafe-swiftshader",
      "--use-angle=swiftshader",
    ],
  });
  try {
    const page = await browser.newPage({
      viewport: MOBILE
        ? { width: 390, height: 844 }
        : { width: 1440, height: 900 },
      deviceScaleFactor: 1,
    });
    page.on("console", (msg) => {
      if (msg.type() === "error") console.log(`  [console.error] ${msg.text()}`);
    });
    page.on("pageerror", (err) => console.log(`  [pageerror] ${err.message}`));

    const shoot = async (s) => {
      const url = `${BASE}?s=${s}&snap=1`;
      console.log(`→ ${url}`);
      // dev 模式 HMR 资源可能拖住 load 事件：等 DOM + canvas 即可
      await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60_000 });
      await page.waitForSelector("canvas", { timeout: 60_000 });
      // 等 WebGL 首帧与出场动画稳定（snap 模式下相机瞬移，只等渲染）
      await page.waitForTimeout(s === 0 ? 3200 : 1800);
      const probe = await page.evaluate(() => {
        const max =
          document.documentElement.scrollHeight - window.innerHeight;
        const store = window.__uvProgress;
        return `scrollY=${Math.round(window.scrollY)} max=${max} p=${(window.scrollY / max).toFixed(4)} store=${store ? store.value.toFixed(4) : "n/a"}`;
      });
      console.log(`  [probe] ${probe}`);
      const file = path.join(
        OUT_DIR,
        `universe_${MOBILE ? "m" : "s"}${s}.png`,
      );
      await page.screenshot({ path: file });
      console.log(`  ✓ ${path.relative(ROOT, file)}`);
    };
    for (let s = 0; s < SECTIONS; s += 1) {
      try {
        await shoot(s);
      } catch (err) {
        console.log(`  retry s=${s}: ${err.message.split("\n")[0]}`);
        await shoot(s);
      }
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
