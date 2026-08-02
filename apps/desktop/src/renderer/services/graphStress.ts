// Dev-only：在已挂载协作图上灌高密度 run_output_delta，配合 __graphPerf 量掉帧。
//
// 开 perf：`__graphPerf()`
// 灌流：`await __graphStress()` 或 `__graphStress({ durationMs: 3000 })`
//
// 仅 DEV；零生产副作用。

import { isGraphPerfEnabled } from "@/services/graphPerf";
import {
  type RunFrame,
  execRuntime,
  useExecutionStore,
} from "@/stores/execution";

export interface GraphStressOptions {
  /** 灌流时长（默认 3000ms）。 */
  durationMs?: number;
  /** 每个 rAF、每个 running worker 追加的字符数（默认 64）。 */
  charsPerTick?: number;
  /** 每 N 个 rAF 才写一次 store（默认 1 = 每帧）。用于 A/B 验证投影节流。 */
  everyNFrames?: number;
}

export interface GraphStressResult {
  ticks: number;
  workers: number;
  messageId: string;
  framesAtEnd: number;
  durationMs: number;
  perfWasOn: boolean;
}

declare global {
  interface Window {
    __graphStress?: (
      opts?: GraphStressOptions,
    ) => Promise<GraphStressResult | null>;
  }
}

function pickLiveMessageId(): string | null {
  const byId = useExecutionStore.getState().byId;
  let best: { id: string; frames: number } | null = null;
  for (const [id, rt] of Object.entries(byId)) {
    if (!rt.plan) continue;
    const n = rt.frames.length;
    if (!best || n > best.frames) best = { id, frames: n };
  }
  return best?.id ?? null;
}

function runningWorkerIds(
  messageId: string,
): { agentId: string; runId: string }[] {
  const rt = execRuntime(useExecutionStore.getState(), messageId);
  if (!rt.plan) return [];
  // Always flood every non-captain plan run (max projection pressure), even if
  // the fixture already settled — deltas still append and refresh faces.
  const out: { agentId: string; runId: string }[] = [];
  for (const run of rt.plan.runs) {
    if (run.kind === "captain") continue;
    out.push({ agentId: run.agentId, runId: run.id });
  }
  return out;
}

async function runStress(
  opts: GraphStressOptions = {},
): Promise<GraphStressResult | null> {
  const durationMs = opts.durationMs ?? 3000;
  const charsPerTick = opts.charsPerTick ?? 64;
  const everyNFrames = Math.max(1, opts.everyNFrames ?? 1);
  const messageId = pickLiveMessageId();
  if (!messageId) {
    console.warn("[graph-stress] no execution in store");
    return null;
  }
  const workers = runningWorkerIds(messageId);
  if (workers.length === 0) {
    console.warn("[graph-stress] no agent runs to flood");
    return null;
  }

  const chunk = "压".repeat(charsPerTick);
  const perfWasOn = isGraphPerfEnabled();
  const t0 = performance.now();
  let ticks = 0;
  let rafCount = 0;
  let seq = Date.now();

  console.info(
    `[graph-stress] flooding ${workers.length} workers for ${durationMs}ms everyN=${everyNFrames} (perf=${perfWasOn ? "on" : "off"})`,
  );

  await new Promise<void>((resolve) => {
    const step = () => {
      if (performance.now() - t0 >= durationMs) {
        resolve();
        return;
      }
      rafCount += 1;
      if (rafCount % everyNFrames === 0) {
        const batch: RunFrame[] = workers.map((w) => ({
          t: seq++,
          kind: "run_output_delta" as const,
          runId: w.runId,
          agentId: w.agentId,
          delta: chunk,
        }));
        useExecutionStore.getState().recordFrames(batch, messageId);
        ticks += 1;
      }
      requestAnimationFrame(step);
    };
    requestAnimationFrame(step);
  });

  const framesAtEnd = execRuntime(useExecutionStore.getState(), messageId)
    .frames.length;
  const result: GraphStressResult = {
    ticks,
    workers: workers.length,
    messageId,
    framesAtEnd,
    durationMs: Math.round(performance.now() - t0),
    perfWasOn,
  };
  console.info("[graph-stress] done", result);
  return result;
}

if (import.meta.env?.DEV && typeof window !== "undefined") {
  window.__graphStress = runStress;
}
