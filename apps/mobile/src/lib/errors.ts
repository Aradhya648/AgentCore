/**
 * Mobile error triage for chat transport refusals (parity with desktop
 * `lib/errors.ts` · RetryBanner「去配置」). Shared code catalog from
 * `@agentcore/contract-types` so both clients route the same BYOK codes.
 */
import { KEY_CONFIG_ERROR_CODES } from "@agentcore/contract-types";

/** One-click remedy that routes the user to fix the cause (not a retry). */
export interface ErrorAction {
  label: string;
  href: string;
}

/** Mobile model-config route (对齐桌面 `/more/model`). */
export const MODEL_CONFIG_PATH = "/more/model";

/**
 * A non-OK SSE channel response that arrived as plain JSON
 * `{ error: { code, message } }` (e.g. 402 LLM_KEY_REQUIRED before the stream
 * opens) rather than an event stream.
 */
export class StreamHttpError extends Error {
  constructor(
    public status: number,
    public code?: string,
    public serverMessage?: string,
  ) {
    super(serverMessage ?? `请求失败 (${status})`);
    this.name = "StreamHttpError";
  }
}

/** Map a backend error `code` to the model-config remedy, or null. */
export function errorActionForCode(
  code: string | undefined,
): ErrorAction | null {
  if (
    code !== undefined &&
    (KEY_CONFIG_ERROR_CODES as readonly string[]).includes(code)
  ) {
    return { label: "去配置", href: MODEL_CONFIG_PATH };
  }
  // 平台额度耗尽 (QUOTA_EXCEEDED, 成本配额与计费 §〇·六 F6): 次级出口「接入自己的 Key」
  // (byok 回合不查配额) — 与桌面对齐; 主文案由后端 message 单一源下发。
  if (code === "QUOTA_EXCEEDED") {
    return { label: "接入自己的 Key", href: MODEL_CONFIG_PATH };
  }
  return null;
}

/** zh message + optional「去配置」 for a refused SSE turn. */
export function describeStreamHttpError(err: StreamHttpError): {
  message: string;
  action: ErrorAction | null;
} {
  let message: string;
  if (err.code === "LLM_KEY_REQUIRED") {
    message =
      err.serverMessage ??
      "请先在「设置 · 模型配置」中填入你的 API Key，再发起对话。";
  } else if (err.serverMessage) {
    message = err.serverMessage;
  } else {
    message = `请求失败 (${err.status})`;
  }
  return { message, action: errorActionForCode(err.code) };
}

/**
 * Draft / empty-chat copy。平台代付、开箱即用——无「先接入模型」门，keyless 亦直接进欢迎态
 * （BYOK 是「更多 → 模型配置」里的可选升级，不在空态拦路）。Pure helper so the empty-state
 * branch stays unit-testable without mounting ChatPage.
 */
export function emptyChatCopy(): {
  title: string;
  subtitle: string;
  action: ErrorAction | null;
} {
  return {
    title: "开始新对话",
    subtitle: "向你的 Agent 团队提问，或交派一个任务。",
    action: null,
  };
}
