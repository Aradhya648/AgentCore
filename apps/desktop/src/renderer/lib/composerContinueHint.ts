import type { Message } from "@/stores/conversation";

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

export const COMPOSER_CONTINUE_PLACEHOLDER = "可输入「继续」接着说…";
