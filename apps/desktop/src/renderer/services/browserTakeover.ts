import { ApiError, api } from "@/services/api";

/**
 * L3「团队浏览器」M2 用户接管客户端 (提案 D16–D18)。
 *
 * 三条 per-conversation REST 通道（区别于 M1 的旁路 SSE 直播帧通道 `services/browserLive`）：
 *  - `POST …/browser/takeover` {action:"start"|"end"} —— 起止接管（仅无 turn 运行时可 start，
 *    失败语义 turn_running / no_session / already_active；end 幂等）。
 *  - `POST …/browser/input` {events:[…]} —— 批量注入用户在直播画面上的输入（**坐标为帧像素空间**
 *    = `browser_live_frame` 的 width/height，前端负责把展示坐标换算到帧空间）。
 *  - `GET …/browser/takeovers` —— 接管留档记录（起止 + 时长），供时间线标记卡重建（D17）。
 *
 * 走 `services/api`（而非 browserLive 的裸 fetch）以复用 401 刷新 / CSRF / `{error:{code}}`
 * 契约——start 的失败语义正是靠 {@link ApiError.code} 分辨（见 {@link takeoverStartErrorMessage}）。
 * 接管态**不走 live 通道**、留档不入 live 帧流（守 M1 已钉三态直播契约）。
 */

/**
 * 一条用户输入事件（**坐标 x/y 为帧像素空间**，非展示坐标）。批量灌进 `…/browser/input`
 * 的 `events`，driver 侧转 CDP Input 域命令注入。三类：
 *  - `mouse`：down/up/move/wheel；`button` 数字（0 左 /1 中 /2 右）；wheel 带 `delta_x/delta_y`。
 *  - `key`：down/up；`key` 为解析后的键值（如 "a" / "Enter"），`code` 物理键，`modifiers` 修饰键名。
 *  - `text`：IME/组合输入兜底——直接灌最终合成文本（不逐键上报）。
 */
export type BrowserInputEvent =
  | {
      kind: "mouse";
      type: "down" | "up" | "move" | "wheel";
      x: number;
      y: number;
      button?: number;
      delta_x?: number;
      delta_y?: number;
      click_count?: number;
    }
  | {
      kind: "key";
      type: "down" | "up";
      key: string;
      code?: string;
      modifiers?: string[];
    }
  | { kind: "text"; text: string };

/** 一条接管留档记录（D17）：起于 `startedAt`，`endedAt` 非空即已归还（带时长）。 */
export interface BrowserTakeoverRecord {
  id: string;
  startedAt: string;
  /** null = 仍接管中 / 未正常归还（异常收尾）——卡片退化为无时长文案。 */
  endedAt: string | null;
}

/** 服务端 wire 形（snake_case）→ narrow 到 renderer 本地 {@link BrowserTakeoverRecord}。 */
interface BrowserTakeoverWire {
  id: string;
  started_at: string;
  ended_at?: string | null;
}

/** start 失败的钉死语义码（`{error:{code}}` 的 code）。 */
export type TakeoverStartErrorCode =
  | "turn_running"
  | "no_session"
  | "already_active";

function takeoverPath(conversationId: string): string {
  return `/v1/conversations/${encodeURIComponent(conversationId)}/browser/takeover`;
}

function inputPath(conversationId: string): string {
  return `/v1/conversations/${encodeURIComponent(conversationId)}/browser/input`;
}

function takeoversPath(conversationId: string): string {
  return `/v1/conversations/${encodeURIComponent(conversationId)}/browser/takeovers`;
}

/**
 * 起接管：仅无 turn 运行时可成功（D16）。失败经 {@link ApiError} 抛出，`code` ∈
 * turn_running / no_session / already_active——调用方以 {@link takeoverStartErrorMessage} 成文。
 */
export async function startBrowserTakeover(
  conversationId: string,
): Promise<void> {
  await api.post<{ ok?: boolean }>(takeoverPath(conversationId), {
    action: "start",
  });
}

/** 归还控制：幂等（重复 end / 会话已亡都安全）。尽力而为，收口路径调用。 */
export async function endBrowserTakeover(
  conversationId: string,
): Promise<void> {
  await api.post<{ ok?: boolean }>(takeoverPath(conversationId), {
    action: "end",
  });
}

/** 批量注入输入事件（坐标须已换算到帧像素空间）。空批不发。 */
export async function sendBrowserInput(
  conversationId: string,
  events: BrowserInputEvent[],
): Promise<void> {
  if (events.length === 0) return;
  await api.post<{ ok?: boolean }>(inputPath(conversationId), { events });
}

/** 拉取本会话接管留档（起止 + 时长），供时间线标记卡重建（D17，刷新/回放可重建）。 */
export function listBrowserTakeovers(
  conversationId: string,
): Promise<BrowserTakeoverRecord[]> {
  return api
    .get<{ takeovers: BrowserTakeoverWire[] }>(takeoversPath(conversationId))
    .then((r) =>
      (r.takeovers ?? []).map((t) => ({
        id: t.id,
        startedAt: t.started_at,
        endedAt: t.ended_at ?? null,
      })),
    );
}

/** 把 start 失败映射成用户可读的 zh 文案（钉死语义码优先，其余回落后端 message）。 */
export function takeoverStartErrorMessage(err: unknown): string {
  const code = err instanceof ApiError ? err.code : undefined;
  switch (code) {
    case "turn_running":
      return "有正在进行的回合，等它结束后再接管";
    case "no_session":
      return "当前没有进行中的浏览器会话";
    case "already_active":
      return "浏览器已被接管";
    default:
      return (
        (err instanceof ApiError && err.serverMessage) ||
        "无法接管浏览器，请重试"
      );
  }
}

/** 展示坐标换算所需的最小矩形（`getBoundingClientRect` 的子集）。 */
export interface DisplayRect {
  left: number;
  top: number;
  width: number;
  height: number;
}

/**
 * 把展示坐标（相对视口的 clientX/clientY）换算到**帧像素空间**。
 *
 * 直播画面按 `object-contain` 等比缩放居中于容器（缩放 + 留白/信箱边），故须：
 * 取 `scale = min(容器宽/帧宽, 容器高/帧高)`、扣掉两侧留白、再除以 scale 还原到帧像素；
 * 最后钳到 [0,帧宽]×[0,帧高] 并取整。帧尺寸非法（≤0）时回落 (0,0)。
 */
export function toFrameSpace(
  clientX: number,
  clientY: number,
  rect: DisplayRect,
  frameWidth: number,
  frameHeight: number,
): { x: number; y: number } {
  if (frameWidth <= 0 || frameHeight <= 0) return { x: 0, y: 0 };
  const scale = Math.min(rect.width / frameWidth, rect.height / frameHeight);
  if (!(scale > 0)) return { x: 0, y: 0 };
  const renderedW = frameWidth * scale;
  const renderedH = frameHeight * scale;
  const padX = (rect.width - renderedW) / 2;
  const padY = (rect.height - renderedH) / 2;
  const fx = (clientX - rect.left - padX) / scale;
  const fy = (clientY - rect.top - padY) / scale;
  const clamp = (v: number, max: number) => Math.max(0, Math.min(max, v));
  return {
    x: Math.round(clamp(fx, frameWidth)),
    y: Math.round(clamp(fy, frameHeight)),
  };
}

/** 从 DOM 键盘事件提取修饰键名数组（空则省略，不发 `modifiers:[]`）。 */
export function modifiersOf(e: {
  altKey: boolean;
  ctrlKey: boolean;
  metaKey: boolean;
  shiftKey: boolean;
}): string[] | undefined {
  const mods: string[] = [];
  if (e.altKey) mods.push("alt");
  if (e.ctrlKey) mods.push("ctrl");
  if (e.metaKey) mods.push("meta");
  if (e.shiftKey) mods.push("shift");
  return mods.length > 0 ? mods : undefined;
}

/** 把毫秒时长成文为「N分M秒」（不足 1 分只显「M秒」）——标记卡时长文案（D17）。 */
export function formatTakeoverDuration(ms: number): string {
  const totalSec = Math.max(0, Math.round(ms / 1000));
  const min = Math.floor(totalSec / 60);
  const sec = totalSec % 60;
  return min > 0 ? `${min}分${sec}秒` : `${sec}秒`;
}

/**
 * 输入批处理器：把高频 DOM 输入攒批后定时 flush（`…/browser/input`），避免事件洪泛（D16）。
 * 连续的鼠标 move 就地合并（只留最新一条），故拖拽/悬停不会灌爆。commit 类事件（up/wheel/
 * text）立即 flush 以求手感。`stop()` 收口：flush 残留 + 停表。发送失败即丢弃该批（不重放陈旧
 * 输入）；缓冲仅在飞、绝不落任何持久缓存（守 D7：密码等键入不回显不留存）。
 */
export interface InputBatcher {
  push: (event: BrowserInputEvent) => void;
  flush: () => void;
  stop: () => void;
}

const DEFAULT_FLUSH_MS = 60;

export function createInputBatcher(
  send: (events: BrowserInputEvent[]) => Promise<void>,
  flushMs: number = DEFAULT_FLUSH_MS,
): InputBatcher {
  let buffer: BrowserInputEvent[] = [];
  let timer: ReturnType<typeof setTimeout> | null = null;
  let stopped = false;

  function flush(): void {
    if (timer !== null) {
      clearTimeout(timer);
      timer = null;
    }
    if (buffer.length === 0) return;
    const batch = buffer;
    buffer = [];
    // Best-effort: a dropped batch = a missed keystroke, acceptable for takeover;
    // replaying stale input would be worse. Never surface / log the content.
    void send(batch).catch(() => {});
  }

  function schedule(): void {
    if (timer !== null || stopped) return;
    timer = setTimeout(() => {
      timer = null;
      flush();
    }, flushMs);
  }

  function isCommit(event: BrowserInputEvent): boolean {
    if (event.kind === "text") return true;
    if (event.kind === "key") return event.type === "up";
    return event.type === "up" || event.type === "wheel";
  }

  return {
    push(event) {
      if (stopped) return;
      const last = buffer[buffer.length - 1];
      if (
        event.kind === "mouse" &&
        event.type === "move" &&
        last?.kind === "mouse" &&
        last.type === "move"
      ) {
        buffer[buffer.length - 1] = event; // coalesce consecutive moves
      } else {
        buffer.push(event);
      }
      if (isCommit(event)) flush();
      else schedule();
    },
    flush,
    stop() {
      stopped = true;
      flush();
    },
  };
}
