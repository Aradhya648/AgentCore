import type { Message } from "@/stores/conversation";

/**
 * Layered recoverability (空中断定案):
 * - Layer 1 (default): send another message = new turn. Empty interrupted gets a
 *   light composer hint only — no retry button / no resume API.
 * - Layer 2: explicit StatusStrip / bubble retry only when there is a nameable
 *   failure (team graph failed runs, transport error, …).
 * - 「继续」placeholder: only when the last assistant has body (接着聊 as a new
 *   message). Never for empty interrupted (no body to continue from).
 */

/** Last-turn salvage that used to surface as 「继续生成」— discoverability now
 * rides the composer placeholder (user types the literal「继续」). */
export function isContinuableAssistant(
  message: Message | undefined | null,
): boolean {
  if (!message || message.role !== "assistant" || message.isStreaming) {
    return false;
  }
  const finishReason = message.finishReason ?? message.runs?.finishReason;
  if (
    finishReason !== "cancelled" &&
    finishReason !== "interrupted" &&
    finishReason !== "max_rounds"
  ) {
    return false;
  }
  return message.content.length > 0;
}

/** Empty interrupted: no body → re-ask via new turn (not continue placeholder). */
export function isEmptyInterruptedAssistant(
  message: Message | undefined | null,
): boolean {
  if (!message || message.role !== "assistant" || message.isStreaming) {
    return false;
  }
  if (message.content.length > 0) return false;
  const finishReason = message.finishReason ?? message.runs?.finishReason;
  return finishReason === "interrupted";
}

export const COMPOSER_CONTINUE_PLACEHOLDER = "可输入「继续」接着说…";

/** Light hint above composer — discoverability only; send is the recovery action. */
export const COMPOSER_EMPTY_INTERRUPTED_HINT =
  "已中断。直接发送下一条即可重试。";
