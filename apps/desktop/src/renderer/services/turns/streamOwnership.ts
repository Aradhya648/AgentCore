/**
 * 会话级 SSE 主路所有权（发送即有流 · midFlight 双连接防交叉）。
 *
 * turn1 的 POST/attach/sidecar 泵持有 primary；midFlight 经典排队在 ``turn_queued``
 * 之后缓冲后续帧，直到 primary 栈清空（turn1 含 followups/turn_saved 的整段泵结束）
 * 再放行 ``message_start``——避免 drain 边界处 resetAssistant 与 turn1 收口帧交错
 * 污染末条气泡。
 *
 * 协调插话不经此门（短确认流即时 dispatch）。入队发生在 POST 时刻（D9 FIFO），
 * 本模块只推迟客户端 fold，不推迟服务端排队。
 */

type Slot = {
  /** 嵌套 claim 栈（sendTurn 外包 + runMessageStream 内包）；空 = 主路空闲。 */
  stack: string[];
  waiters: Array<() => void>;
};

const slots = new Map<string, Slot>();

function slotOf(conversationId: string): Slot {
  let s = slots.get(conversationId);
  if (!s) {
    s = { stack: [], waiters: [] };
    slots.set(conversationId, s);
  }
  return s;
}

export function claimPrimaryStream(conversationId: string): string {
  const token = crypto.randomUUID();
  slotOf(conversationId).stack.push(token);
  return token;
}

export function releasePrimaryStream(
  conversationId: string,
  token: string,
): void {
  const s = slots.get(conversationId);
  if (!s) return;
  const idx = s.stack.lastIndexOf(token);
  if (idx < 0) return;
  s.stack.splice(idx, 1);
  if (s.stack.length === 0) {
    const waiters = s.waiters.splice(0);
    for (const w of waiters) w();
    if (s.waiters.length === 0 && s.stack.length === 0) {
      slots.delete(conversationId);
    }
  }
}

export function isPrimaryStreamIdle(conversationId: string): boolean {
  const s = slots.get(conversationId);
  return !s || s.stack.length === 0;
}

/** 主路变为空闲时回调一次（已空闲则仍登记，等下次 release；即时空闲请先查 idle）。 */
export function onPrimaryStreamIdle(
  conversationId: string,
  cb: () => void,
): () => void {
  const s = slotOf(conversationId);
  s.waiters.push(cb);
  return () => {
    const i = s.waiters.indexOf(cb);
    if (i >= 0) s.waiters.splice(i, 1);
  };
}

export function waitForPrimaryStreamIdle(
  conversationId: string,
): Promise<void> {
  if (isPrimaryStreamIdle(conversationId)) return Promise.resolve();
  return new Promise((resolve) => {
    const unsub = onPrimaryStreamIdle(conversationId, () => {
      unsub();
      resolve();
    });
  });
}

/** 测试隔离：清空所有会话的所有权态。 */
export function resetStreamOwnershipForTests(): void {
  slots.clear();
}
