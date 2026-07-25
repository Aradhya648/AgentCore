// 协作图「运行中节点偶发消失」假跑探针。
// 开 graphTrace → 快速 scrub #/preview 中间帧 → 收集 projection/layout/dom_clip 异常。
//
// Usage:
//   pnpm -C apps/desktop shoot:graph-missing
//   pnpm -C apps/desktop shoot:graph-missing -- multi_agent_multi_lens_research
//   pnpm -C apps/desktop shoot:graph-missing -- multi_agent_coordination_wait 40
//
// Args: [scenario] [maxFrame]
// Output: shoot-out-graph-missing/<scenario>-report.json

import { mkdir, writeFile } from "node:fs/promises";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { chromium } from "playwright";
import { createServer } from "vite";

const here = dirname(fileURLToPath(import.meta.url));
const desktopDir = resolve(here, "..");
const outDir = resolve(desktopDir, "shoot-out-graph-missing");
const SCENARIO = process.argv[2] || "multi_agent_multi_lens_research";
const MAX_FRAME = Math.max(1, Number(process.argv[3] ?? 48) | 0);
/** 故意短 settle：抓测高/ELK 窗口，不要等完全稳定。 */
const SETTLE_MS = 120;
const SAMPLE_EVERY = 2;

function summarizeDump(events) {
  const byKind = {};
  const anomalies = [];
  for (const ev of events) {
    byKind[ev.kind] = (byKind[ev.kind] ?? 0) + 1;
    if (
      ev.detail?.anomaly ||
      ev.detail?.gap ||
      (ev.detail?.missingPosIds && ev.detail.missingPosIds.length) ||
      (ev.detail?.clippedIds && ev.detail.clippedIds.length) ||
      (ev.detail?.missing && ev.detail.missing.length)
    ) {
      anomalies.push(ev);
    }
  }
  return { byKind, anomalyCount: anomalies.length, anomalies };
}

async function probeDom(page) {
  return page.evaluate(() => {
    const flow = document.querySelector(".react-flow");
    if (!flow) {
      return { rf: false, nodeCount: 0, agentLike: 0, clippedIds: [] };
    }
    const c0 = flow.getBoundingClientRect();
    const nodes = [...document.querySelectorAll(".react-flow__node")].map(
      (el) => {
        const r = el.getBoundingClientRect();
        return {
          id: el.getAttribute("data-id"),
          type: [...el.classList].find((c) =>
            c.startsWith("react-flow__node-"),
          ),
          top: r.top,
          bottom: r.bottom,
        };
      },
    );
    const clippedIds = nodes
      .filter(
        (n) => n.id && n.top < c0.bottom && n.bottom > c0.bottom + 1,
      )
      .map((n) => n.id);
    const agentLike = nodes.filter((n) =>
      /node-(agent|captain)/.test(n.type ?? ""),
    ).length;
    return {
      rf: true,
      nodeCount: nodes.length,
      agentLike,
      clippedIds,
      containerH: Math.round(c0.height),
      ids: nodes.map((n) => n.id).filter(Boolean),
    };
  });
}

async function main() {
  process.chdir(desktopDir);
  await mkdir(outDir, { recursive: true });

  console.log("Booting vite…");
  const server = await createServer({
    configFile: resolve(desktopDir, "vite.web.config.ts"),
    logLevel: "warn",
  });
  await server.listen();
  const base = server.resolvedUrls?.local?.[0];
  if (!base) {
    await server.close();
    throw new Error("no vite URL");
  }

  const browser = await chromium.launch();
  const page = await browser.newPage({
    viewport: { width: 1440, height: 900 },
    deviceScaleFactor: 1,
    colorScheme: "light",
  });
  await page.addInitScript(() => {
    try {
      localStorage.setItem("agentcore:theme", "light");
      localStorage.setItem("agentcore:side-panel-open", "false");
      localStorage.setItem("graphTrace", "1");
    } catch {
      /* */
    }
  });

  const consoleLines = [];
  page.on("console", (msg) => {
    const text = msg.text();
    if (text.includes("[graph-trace]")) consoleLines.push(text);
  });

  const frames = [];
  let boot = true;
  for (let k = 1; k <= MAX_FRAME; k += SAMPLE_EVERY) {
    const url = new URL("index.web.html", base);
    url.hash = `/preview?s=${encodeURIComponent(SCENARIO)}&k=${k}`;
    try {
      await page.goto(url.href, {
        waitUntil: boot ? "load" : "domcontentloaded",
        timeout: 30_000,
      });
      boot = false;
      await page.waitForSelector(
        `[data-preview-scenario="${SCENARIO}"][data-preview-frame="${k}"]`,
        { timeout: 12_000 },
      );
      await page.waitForTimeout(SETTLE_MS);
      // 确保模块已挂上开关（localStorage 已在 init 打开）
      await page.evaluate(() => {
        window.__graphTrace?.(true);
      });
      const dom = await probeDom(page);
      const dump = await page.evaluate(() => window.__graphTrace?.dump?.() ?? []);
      const summary = summarizeDump(dump);
      frames.push({
        k,
        dom,
        anomalyCount: summary.anomalyCount,
        lastAnomalies: summary.anomalies.slice(-5),
      });
      if (dom.clippedIds.length || summary.anomalyCount > 0) {
        console.log(
          `k=${k} agents=${dom.agentLike} clipped=${JSON.stringify(dom.clippedIds)} anomalies=${summary.anomalyCount}`,
        );
      } else {
        process.stdout.write(`.`);
      }
      await page.evaluate(() => window.__graphTrace?.clear?.());
    } catch (err) {
      frames.push({ k, error: String(err?.message ?? err) });
      console.log(`\nk=${k} ERROR ${err?.message ?? err}`);
    }
  }
  console.log("");

  // full settle 对照
  {
    const url = new URL("index.web.html", base);
    url.hash = `/preview?s=${encodeURIComponent(SCENARIO)}`;
    await page.goto(url.href, { waitUntil: "load", timeout: 30_000 });
    await page.waitForSelector(
      `[data-preview-scenario="${SCENARIO}"][data-preview-frame="full"]`,
      { timeout: 20_000 },
    );
    await page.waitForTimeout(2500);
    await page.evaluate(() => window.__graphTrace?.(true));
    const dom = await probeDom(page);
    const dump = await page.evaluate(() => window.__graphTrace?.dump?.() ?? []);
    frames.push({
      k: "full",
      settleMs: 2500,
      dom,
      dumpSummary: summarizeDump(dump),
    });
    await page.screenshot({
      path: resolve(outDir, `${SCENARIO}-full.png`),
      fullPage: false,
    });
  }

  const clippedFrames = frames.filter(
    (f) => f.dom?.clippedIds?.length > 0,
  );
  const projectionGaps = frames.filter((f) =>
    (f.lastAnomalies ?? f.dumpSummary?.anomalies ?? []).some(
      (a) => a.kind === "projection" || a.kind === "layout_ok",
    ),
  );

  const report = {
    scenario: SCENARIO,
    settleMs: SETTLE_MS,
    maxFrame: MAX_FRAME,
    sampleEvery: SAMPLE_EVERY,
    frameCount: frames.length,
    clippedFrameCount: clippedFrames.length,
    projectionOrLayoutGapFrames: projectionGaps.length,
    clippedFrames: clippedFrames.map((f) => ({
      k: f.k,
      clippedIds: f.dom.clippedIds,
      agentLike: f.dom.agentLike,
      containerH: f.dom.containerH,
      ids: f.dom.ids,
    })),
    projectionOrLayoutGapSamples: projectionGaps.slice(0, 20),
    consoleSample: consoleLines.slice(0, 80),
    frames,
  };

  const reportPath = resolve(outDir, `${SCENARIO}-report.json`);
  await writeFile(reportPath, JSON.stringify(report, null, 2), "utf8");
  console.log("Wrote", reportPath);
  console.log(
    `Summary: clippedFrames=${clippedFrames.length} projection/layoutGaps=${projectionGaps.length}`,
  );

  await browser.close();
  await server.close();

  // 非零：便于一眼看到「抓到异常」；无异常也 exit 0（探针本身成功）
  if (clippedFrames.length || projectionGaps.length) {
    console.log("FOUND anomalies — inspect report for root-cause signal.");
  } else {
    console.log("No clip/projection anomalies in sampled frames (try other scenario / shorter settle).");
  }
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
