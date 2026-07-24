// Dev-only 回合生命周期探针：抓 sendTurn 里 POST 发出前 → 首条 SSE 的盲区。
// `__sseTrace()` 只管 SSE 开始后；本探针补「正在思考…」卡住时 fetch / sidecar 探活段。
//
// 开：DevTools 执行 `__turnTrace()`（或 `localStorage.turnTrace = "1"` 后刷新）
// 关：`__turnTrace(false)`
//
// 纯诊断、零生产副作用。

interface TurnTrace {
  start: number;
  milestones: string[];
}

const traces = new Map<string, TurnTrace>();

let _on = false;

declare global {
  interface Window {
    /** Dev 回合生命周期探针。`__turnTrace()` 开、`__turnTrace(false)` 关。 */
    __turnTrace?: (on?: boolean) => boolean;
  }
}

if (import.meta.env.DEV && typeof window !== "undefined") {
  try {
    _on = window.localStorage?.getItem("turnTrace") === "1";
  } catch {
    /* localStorage 不可用 */
  }
  window.__turnTrace = (on = true): boolean => {
    _on = on;
    try {
      if (on) window.localStorage.setItem("turnTrace", "1");
      else window.localStorage.removeItem("turnTrace");
    } catch {
      /* 持久化失败无妨 */
    }
    console.info(
      `[turn-trace] ${on ? "ON — 发一条消息看 sendTurn 里程碑" : "off"}`,
    );
    return _on;
  };
}

function enabled(): boolean {
  return import.meta.env.DEV && _on;
}

function short(id: string): string {
  return id.length > 8 ? id.slice(0, 8) : id;
}

function ensure(conversationId: string): TurnTrace {
  let t = traces.get(conversationId);
  if (!t) {
    t = { start: performance.now(), milestones: [] };
    traces.set(conversationId, t);
  }
  return t;
}

/** 记录 sendTurn / stream 链路上的一个里程碑（仅 dev + 开关开时）。 */
export function traceTurnMilestone(
  conversationId: string,
  label: string,
  detail?: Record<string, unknown>,
): void {
  if (!enabled()) return;
  const t = ensure(conversationId);
  const ms = Math.round(performance.now() - t.start);
  const extra = detail ? ` ${JSON.stringify(detail)}` : "";
  const line = `+${ms}ms ${label}${extra}`;
  t.milestones.push(line);
  console.info(`[turn-trace] conv=${short(conversationId)} ${line}`);
}

/** 回合结束（成功 / 失败 / finally）时 dump 里程碑并清状态。 */
export function traceTurnEnd(
  conversationId: string,
  outcome: "ok" | "error" | "abort",
): void {
  if (!enabled()) return;
  const t = traces.get(conversationId);
  if (!t) return;
  const total = Math.round(performance.now() - t.start);
  console.group(
    `[turn-trace] conv=${short(conversationId)} end=${outcome} total=${total}ms`,
  );
  for (const line of t.milestones) console.info(line);
  console.groupEnd();
  traces.delete(conversationId);
}

/** 首条 SSE 事件到达（与 __sseTrace 互补，标出 POST→首字节的尾部延迟）。 */
export function traceTurnFirstSSE(
  conversationId: string,
  eventType: string,
): void {
  if (!enabled()) return;
  const t = traces.get(conversationId);
  if (!t || t.milestones.some((m) => m.includes("first_sse"))) return;
  traceTurnMilestone(conversationId, "first_sse", { type: eventType });
}
