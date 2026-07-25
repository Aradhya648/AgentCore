import { ApiError, api } from "@/services/api";

/**
 * L3「团队浏览器」M2 用户接管客户端 (提案 D16–D18)。
 *
 * 三条 per-conversation REST 通道（区别于 M1 的旁路 SSE 直播帧通道 `services/browserLive`）：
 *  - `POST …/browser/takeover` {action:"start"|"end"} —— 起止接管。响应体为
 *    {@link BrowserTakeoverState}（200 + `reason`），**不**靠 HTTP error code 分辨成败：
 *    start 成功 = `started` | `already_active`；其余 reason（`turn_running` / `no_session` /
 *    `not_active` …）由调用方以 {@link takeoverStartErrorMessage} 成文。登录等待 escalate
 *    pending 期间后端会放行 start（即便有 turn 在跑）。
 *  - `POST …/browser/input` {events:[…]} —— 批量注入用户在直播画面上的输入（**坐标为帧像素空间**
 *    = `browser_live_frame` 的 width/height，前端负责把展示坐标换算到帧空间）。
 *  - `GET …/browser/takeovers` —— `{ data: BrowserTakeoverRecord[] }` 接管留档（起止 + 时长），
 *    供时间线标记卡重建（D17）。
 *
 * 走 `services/api`（而非 browserLive 的裸 fetch）以复用 401 刷新 / CSRF。
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

/** POST …/browser/takeover 响应体的 reason（成败都走 200）。 */
export type BrowserTakeoverReason =
  | "started"
  | "ended"
  | "already_active"
  | "turn_running"
  | "no_session"
  | "not_active";

/** POST …/browser/takeover 的 200 响应体。 */
export interface BrowserTakeoverState {
  active: boolean;
  reason: BrowserTakeoverReason;
  record_id?: string | null;
  started_at?: string | null;
}

/** start 未成功时抛出——`reason` 给 {@link takeoverStartErrorMessage} 成文。 */
export class TakeoverStartError extends Error {
  readonly reason: string;
  constructor(reason: string) {
    super(reason);
    this.name = "TakeoverStartError";
    this.reason = reason;
  }
}

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
 * 起接管。解析 200 响应的 {@link BrowserTakeoverState}：`started` | `already_active` 算成功并
 * 返回 state；其余 reason 抛 {@link TakeoverStartError}（调用方以
 * {@link takeoverStartErrorMessage} 成文）。
 */
export async function startBrowserTakeover(
  conversationId: string,
): Promise<BrowserTakeoverState> {
  const state = await api.post<BrowserTakeoverState>(
    takeoverPath(conversationId),
    { action: "start" },
  );
  if (state.reason === "started" || state.reason === "already_active") {
    return state;
  }
  throw new TakeoverStartError(state.reason);
}

/** 归还控制：幂等（重复 end / 会话已亡都安全）。尽力而为，收口路径调用。 */
export async function endBrowserTakeover(
  conversationId: string,
): Promise<void> {
  await api.post<BrowserTakeoverState>(takeoverPath(conversationId), {
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
    .get<{ data: BrowserTakeoverWire[] }>(takeoversPath(conversationId))
    .then((r) =>
      (r.data ?? []).map((t) => ({
        id: t.id,
        startedAt: t.started_at,
        endedAt: t.ended_at ?? null,
      })),
    );
}

/**
 * 把 start 失败映射成用户可读的 zh 文案。优先吃 reason 字符串（{@link TakeoverStartError} /
 * 裸字符串）；兼容旧 {@link ApiError.code} 路径。
 */
export function takeoverStartErrorMessage(err: unknown): string {
  const reason =
    err instanceof TakeoverStartError
      ? err.reason
      : typeof err === "string"
        ? err
        : err instanceof ApiError
          ? err.code
          : undefined;
  switch (reason) {
    case "turn_running":
      return "有正在进行的回合，等它结束后再接管";
    case "no_session":
      return "当前没有进行中的浏览器会话";
    case "already_active":
      return "浏览器已被接管";
    case "not_active":
      return "当前没有进行中的接管";
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
