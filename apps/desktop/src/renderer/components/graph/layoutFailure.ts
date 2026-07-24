/**
 * ELK 布局失败路径的纯函数——hook catch 与单测共用，避免 layoutReady 永假且无可见态。
 * 不做自动重试 / 自愈。
 */
import { logEvent } from "@/lib/log";

export const LAYOUT_FAILURE_USER_MESSAGE = "无法计算节点位置，图暂时不可用。";

/** 把 catch 到的未知错误收成可展示 / 可日志的短文案。 */
export function describeLayoutFailure(err: unknown): string {
  if (err instanceof Error) {
    const msg = err.message.trim();
    if (msg) return msg;
  }
  if (typeof err === "string") {
    const msg = err.trim();
    if (msg) return msg;
  }
  return LAYOUT_FAILURE_USER_MESSAGE;
}

/** 布局失败时写产品日志（无 preload 时回退 console）。 */
export function logLayoutFailure(
  err: unknown,
  fields?: Record<string, unknown>,
): string {
  const message = describeLayoutFailure(err);
  logEvent("error", "graph.layout_failed", {
    message,
    ...fields,
  });
  return message;
}
