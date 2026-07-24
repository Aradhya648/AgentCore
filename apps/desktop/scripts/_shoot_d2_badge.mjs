/**
 * One-shot: witness preview → 打开辩论室 → 辩论室 tab → click #e2 badge → popover.
 * Dev-only helper for D2 acceptance; not part of CI shoot gate.
 */
import { mkdir } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { createServer } from "vite";

const desktopDir = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const outDir = resolve(desktopDir, "shoot-out");

process.chdir(desktopDir);
await mkdir(outDir, { recursive: true });

const server = await createServer({
  configFile: resolve(desktopDir, "vite.web.config.ts"),
  logLevel: "warn",
});
await server.listen();
const base = server.resolvedUrls?.local?.[0];
if (!base) throw new Error("no vite url");

const browser = await chromium.launch();
const page = await browser.newPage({
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 2,
});
await page.addInitScript(() => {
  localStorage.setItem("agentcore:theme", "light");
  localStorage.setItem("agentcore:side-panel-open", "false");
});

const url = new URL("index.web.html", base);
url.hash = "/preview?s=multi_agent_mlr_debate_witness";
await page.goto(url.href, { waitUntil: "load", timeout: 30_000 });
await page.waitForSelector(
  '[data-preview-scenario="multi_agent_mlr_debate_witness"]',
  { timeout: 15_000 },
);
await page.waitForTimeout(2000);

// 状态条 CTA（辩论回合）
const openBtn = page.getByRole("button", { name: /打开辩论室|在画布打开/ });
console.log("open CTA count:", await openBtn.count());
await openBtn.first().click({ timeout: 8000 });
await page.waitForTimeout(1500);
// 强制辩论室 view（混合图默认协作图）
await page.evaluate(() => {
  const h = location.hash;
  if (!h.includes("/turn/")) return;
  const [path, qs] = h.split("?");
  const params = new URLSearchParams(qs || "");
  params.set("view", "debate");
  location.hash = `${path}?${params.toString()}`;
});
await page.waitForTimeout(1500);
console.log("hash:", await page.evaluate(() => location.hash));

await page.screenshot({
  path: resolve(outDir, "d2_dossier_badge_arena.png"),
});

// #e2 案卷条目徽章文案优先 site=法律；勿点到证人 #e1（无 dossier_path）
// 展开支持方全文（论点折叠行可能盖住徽章）
await page
  .getByRole("button", { name: /第十二条可解除/ })
  .first()
  .click({ force: true })
  .catch(() => {});
await page.waitForTimeout(500);

const labels = await page.evaluate(() =>
  [...document.querySelectorAll("button")].map((b) => b.getAttribute("aria-label")).filter((s) => s?.includes("已核实")),
);
console.log("aria labels:", labels);

const dossierBadge = page.getByRole("button", {
  name: /已核实 · 法律（查看来源）/,
});
await dossierBadge.first().click({ force: true, timeout: 5000 });
await page.waitForTimeout(900);

// Popover 在 portal 里——等「案卷来源」文案
await page.getByText("案卷来源").first().waitFor({ timeout: 3000 }).catch(() => {});

const out = resolve(outDir, "d2_dossier_badge_popover.png");
await page.screenshot({ path: out });
const pop = await page.locator("[data-radix-popper-content-wrapper]").innerText().catch(() => "");
console.log("wrote", out);
console.log("popover text:", pop.slice(0, 400));

await browser.close();
await server.close();
