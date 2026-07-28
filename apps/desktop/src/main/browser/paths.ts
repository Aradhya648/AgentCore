/**
 * LocalChromiumHost 外网页分区工厂 + bounds 归一化（纯逻辑，无 electron）。
 *
 * L1b：外网 http(s) 与工作区 HTML **均**按 conversationId 切开（见 §2.2）；
 * 绝不复用 PREVIEW_PARTITION / defaultSession，也绝不复用彼此。
 */

import type { BrowserBounds } from "@shared/browser-contract";

/** 外网 partition 前缀（完整键 = {@link browserPartitionFor}）。 */
export const BROWSER_PARTITION_PREFIX = "agentcore-browser";

/**
 * 本机浏览器**外网页**所用的**非持久独立分区**（无 `persist:` → 内存态）。
 * 键：`agentcore-browser:conv:{conversationId}`。
 */
export function browserPartitionFor(conversationId: string): string {
  const cid = normalizeBrowserConversationId(conversationId);
  if (!cid) {
    throw new Error("browserPartitionFor: conversationId required");
  }
  return `${BROWSER_PARTITION_PREFIX}:conv:${cid}`;
}

/** 规范化对话 id（trim + 小写）；空串 → ""。 */
export function normalizeBrowserConversationId(
  conversationId: string | null | undefined,
): string {
  if (typeof conversationId !== "string") return "";
  return conversationId.trim().toLowerCase();
}

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
