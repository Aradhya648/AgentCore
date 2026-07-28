/**
 * LocalChromiumHost 外网页分区常量 + bounds 归一化（纯逻辑，无 electron）。
 *
 * L1b：外网 http(s) 用 {@link BROWSER_PARTITION}；工作区 HTML 用
 * `workspace-paths.WORKSPACE_PARTITION`——**绝不**复用彼此，也绝不复用
 * PREVIEW_PARTITION / defaultSession。
 */

import type { BrowserBounds } from "@shared/browser-contract";

/**
 * 本机浏览器**外网页**所用的**非持久独立分区**（无 `persist:` → 内存态）。
 * 与 `agentcore-preview`、`agentcore-browser-workspace`、defaultSession 隔离。
 */
export const BROWSER_PARTITION = "agentcore-browser";

/**
 * 校验并归一化占位 bounds（来自 renderer）：四字段有限数字、取整、宽高钳非负；否则 null。
 */
export function normalizeBrowserBounds(value: unknown): BrowserBounds | null {
  if (typeof value !== "object" || value === null) return null;
  const b = value as Record<string, unknown>;
  const { x, y, width, height } = b;
  if (
    typeof x !== "number" ||
    typeof y !== "number" ||
    typeof width !== "number" ||
    typeof height !== "number" ||
    !Number.isFinite(x) ||
    !Number.isFinite(y) ||
    !Number.isFinite(width) ||
    !Number.isFinite(height)
  ) {
    return null;
  }
  return {
    x: Math.round(x),
    y: Math.round(y),
    width: Math.max(0, Math.round(width)),
    height: Math.max(0, Math.round(height)),
  };
}
