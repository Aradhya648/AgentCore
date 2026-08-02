/**
 * 真 OS 浮窗（方案 C）IPC 契约 —— 主进程 / preload / renderer 三端共享。
 *
 * 桌面「弹出」= 独立 BrowserWindow（对标 JetBrains Window / VS Code Aux）。
 * Web 无真窗，不注入本 API。详见 docs/04-前端/前端UX设计.md §十。
 */

/** 与右坞应用内浮层同一上限。 */
export const FLOAT_WINDOW_MAX = 8;

export const FLOAT_WINDOW_CHANNELS = {
  /** 渲染→主：创建或聚焦同 tabId 真窗；满上限回 false。 */
  open: "float-window:open",
  /** 渲染→主：关窗并钉回（reason=dock）。 */
  dock: "float-window:dock",
  /** 渲染→主：关窗并销毁语义（reason=destroy）。 */
  destroy: "float-window:destroy",
  /** 主→渲染（主窗）：真窗已关。 */
  closed: "float-window:closed",
} as const;

export type FloatWindowCloseReason = "dock" | "destroy" | "user";

export interface FloatWindowBounds {
  x: number;
  y: number;
  width: number;
  height: number;
}

export interface FloatWindowOpenInput {
  tabId: string;
  conversationId: string;
  title: string;
  bounds?: FloatWindowBounds;
}

export interface FloatWindowTabInput {
  tabId: string;
}

export interface FloatWindowClosedPayload {
  tabId: string;
  reason: FloatWindowCloseReason;
}

export interface FloatWindowApi {
  /** @returns false = 满上限或入参无效；true = 已创建或已聚焦既有窗。 */
  open: (input: FloatWindowOpenInput) => Promise<boolean>;
  dock: (input: FloatWindowTabInput) => Promise<void>;
  destroy: (input: FloatWindowTabInput) => Promise<void>;
  /** 订阅主窗侧「真窗已关」；返回退订。 */
  onClosed: (cb: (payload: FloatWindowClosedPayload) => void) => () => void;
}
