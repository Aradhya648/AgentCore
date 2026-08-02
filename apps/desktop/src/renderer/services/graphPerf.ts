// Dev-only 协作图掉帧探针：量 flush / 投影 / ELK 耗时，不改生产路径。
//
// 开：DevTools `__graphPerf()`（刷新后仍开，经 uiStorage）
// 关：`__graphPerf(false)`
// dump：`__graphPerf.dump()` → 环形样本；`.summary()` → 近窗聚合
//
// 默认定时每 2s 打一行汇总；单次 >16ms 立刻 warn。零生产副作用。

import { uiGet, uiSet } from "@/lib/uiStorage";

const GRAPH_PERF_KEY = "graphPerf";
const RING_MAX = 400;
const SUMMARY_MS = 2000;
const LONG_MS = 16;

export type GraphPerfKind = "flush" | "project" | "elk" | "longtask";

export interface GraphPerfSample {
  t: number;
  kind: GraphPerfKind;
  ms: number;
  detail: Record<string, unknown>;
}

const ring: GraphPerfSample[] = [];
const start = performance.now();

let _on = false;
let summaryTimer: ReturnType<typeof setInterval> | null = null;
let longTaskObs: PerformanceObserver | null = null;
let windowStart = 0;
let windowIdx = 0;

declare global {
  interface Window {
    /** Dev 协作图掉帧探针。`__graphPerf()` 开、`__graphPerf(false)` 关；`.dump()` / `.summary()`。 */
    __graphPerf?: ((on?: boolean) => boolean) & {
      dump?: () => GraphPerfSample[];
      summary?: () => Record<string, unknown>;
      clear?: () => void;
    };
  }
}

function percentile(sorted: number[], p: number): number {
  if (sorted.length === 0) return 0;
  const i = Math.min(
    sorted.length - 1,
    Math.max(0, Math.ceil((p / 100) * sorted.length) - 1),
  );
  return sorted[i] ?? 0;
}

function summarizeSlice(fromIdx: number): Record<string, unknown> {
  const slice = ring.slice(fromIdx);
  const byKind: Record<string, number[]> = {};
  for (const s of slice) {
    let bucket = byKind[s.kind];
    if (!bucket) {
      bucket = [];
      byKind[s.kind] = bucket;
    }
    bucket.push(s.ms);
  }
  const out: Record<string, unknown> = {
    samples: slice.length,
    windowMs: Math.round(performance.now() - windowStart),
  };
  for (const [kind, vals] of Object.entries(byKind)) {
    const sorted = [...vals].sort((a, b) => a - b);
    const long = vals.filter((v) => v > LONG_MS).length;
    out[kind] = {
      n: vals.length,
      long,
      p50: Math.round(percentile(sorted, 50) * 10) / 10,
      p95: Math.round(percentile(sorted, 95) * 10) / 10,
      max: Math.round((sorted[sorted.length - 1] ?? 0) * 10) / 10,
    };
  }
  return out;
}

function stopObservers(): void {
  if (summaryTimer != null) {
    clearInterval(summaryTimer);
    summaryTimer = null;
  }
  if (longTaskObs) {
    longTaskObs.disconnect();
    longTaskObs = null;
  }
}

function startObservers(): void {
  stopObservers();
  windowStart = performance.now();
  windowIdx = ring.length;
  summaryTimer = setInterval(() => {
    if (!_on) return;
    const summary = summarizeSlice(windowIdx);
    windowIdx = ring.length;
    windowStart = performance.now();
    console.info("[graph-perf] summary", summary);
  }, SUMMARY_MS);

  if (typeof PerformanceObserver === "undefined") return;
  try {
    longTaskObs = new PerformanceObserver((list) => {
      if (!_on) return;
      for (const entry of list.getEntries()) {
        push("longtask", entry.duration, {
          name: entry.name,
          startTime: Math.round(entry.startTime),
        });
      }
    });
    longTaskObs.observe({ type: "longtask", buffered: false });
  } catch {
    // Chromium only; ignore if unsupported.
    longTaskObs = null;
  }
}

// Optional: tsx conformance has no Vite `import.meta.env`.
if (import.meta.env?.DEV && typeof window !== "undefined") {
  _on = uiGet<boolean>(GRAPH_PERF_KEY) === true;
  const api = ((on = true): boolean => {
    _on = on;
    uiSet(GRAPH_PERF_KEY, on ? true : undefined);
    if (on) {
      startObservers();
      console.info(
        "[graph-perf] ON — 流式跑一轮后看 summary / dump；关：__graphPerf(false)",
      );
    } else {
      stopObservers();
      console.info("[graph-perf] off");
    }
    return _on;
  }) as NonNullable<Window["__graphPerf"]>;
  api.dump = (): GraphPerfSample[] => ring.slice();
  api.summary = (): Record<string, unknown> => summarizeSlice(0);
  api.clear = (): void => {
    ring.length = 0;
    windowIdx = 0;
    windowStart = performance.now();
  };
  window.__graphPerf = api;
  if (_on) startObservers();
}

function enabled(): boolean {
  return Boolean(import.meta.env?.DEV) && _on;
}

function push(
  kind: GraphPerfKind,
  ms: number,
  detail: Record<string, unknown>,
): void {
  if (!enabled()) return;
  const sample: GraphPerfSample = {
    t: Math.round(performance.now() - start),
    kind,
    ms: Math.round(ms * 10) / 10,
    detail,
  };
  ring.push(sample);
  if (ring.length > RING_MAX) ring.shift();
  if (sample.ms > LONG_MS) {
    console.warn(
      `[graph-perf] +${sample.t}ms ${kind} ${sample.ms}ms ${JSON.stringify(detail)}`,
    );
  }
}

/** 记一次热路径耗时（仅 DEV + 已开）。 */
export function markGraphPerf(
  kind: Exclude<GraphPerfKind, "longtask">,
  ms: number,
  detail: Record<string, unknown> = {},
): void {
  push(kind, ms, detail);
}

export function isGraphPerfEnabled(): boolean {
  return enabled();
}
