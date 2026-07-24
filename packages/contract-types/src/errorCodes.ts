// AgentCore error-code contract — the single shared directory of user-facing error
// codes for BOTH desktop and mobile. The code list is generated from the backend
// ErrorCode StrEnum (`pnpm gen:types` → errorCodes.generated.ts). Policy overlays
// below (key-config remedy / non-retriable) stay hand-written — they are client UX
// data, not the catalog itself.

import { ERROR_CODES, type ErrorCode } from "./errorCodes.generated";

export { ERROR_CODES, type ErrorCode };

/** Codes whose remedy is to (re)configure the BYOK key in 设置·模型配置 — the client
 * offers a one-click "去配置" route instead of a retry. `LLM_INSUFFICIENT_BALANCE` is
 * deliberately NOT here: its fix is DeepSeek's billing page (surfaced via the backend's
 * own message), not AgentCore's key settings. */
export const KEY_CONFIG_ERROR_CODES: readonly ErrorCode[] = [
  "LLM_KEY_REQUIRED",
  "LLM_KEY_INVALID",
  // Monthly free tier spent — the remedy is the same one-click "去配置" route
  // (configure a BYOK key to continue unlimited), per 成本配额与计费 §〇·五 D5.
  "FREE_TIER_EXHAUSTED",
];

/** Codes where an immediate retry is pointless until the user acts — top up the wallet,
 * fix/add the key, wait for quota, or fix server config. The client suppresses the
 * retry affordance for these (rate limits stay retriable: they clear on their own). */
export const NON_RETRIABLE_ERROR_CODES: readonly ErrorCode[] = [
  "QUOTA_EXCEEDED",
  "FREE_TIER_EXHAUSTED",
  "LLM_KEY_REQUIRED",
  "LLM_KEY_INVALID",
  "LLM_INSUFFICIENT_BALANCE",
  "KEY_STORAGE_UNAVAILABLE",
  "PLATFORM_BILLING_UNAVAILABLE",
];

/** Type guard: whether `code` is a code the clients recognize (typed against the
 * shared catalog), letting call sites narrow an opaque wire string to `ErrorCode`. */
export function isKnownErrorCode(code: string | undefined): code is ErrorCode {
  return (
    code !== undefined && (ERROR_CODES as readonly string[]).includes(code)
  );
}
