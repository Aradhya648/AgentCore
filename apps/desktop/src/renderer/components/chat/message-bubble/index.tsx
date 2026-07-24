import { isExecutionHarvestMessage } from "@/lib/executionHarvest";
import { useActiveMessageFocus } from "@/stores/conversation";
import { memo, useEffect, useRef } from "react";
import { HarvestSystemChip } from "../HarvestSystemChip";
import { AssistantMessage } from "./AssistantMessage";
import { UserMessage } from "./UserMessage";
import type { MessageBubbleProps } from "./types";

/**
 * 长输出流式性能 (白屏卡死修复·Stage 3): a streaming turn rewrites ONLY the last message
 * object each rAF tick — the conversation store's append mutators spread a fresh object
 * for the tail and keep every earlier message's identity — so memoizing on the `message`
 * reference lets every finished bubble skip the per-tick re-render; only the live tail
 * re-renders while the model streams. The focus subscription still re-runs all bubbles on
 * a jump-to-message (rare), which is what drives scroll-into-view.
 */
export const MessageBubble = memo(function MessageBubble({
  message,
}: MessageBubbleProps) {
  const focus = useActiveMessageFocus();
  const ref = useRef<HTMLDivElement>(null);

  // biome-ignore lint/correctness/useExhaustiveDependencies: focus.nonce is an intentional re-run key
  useEffect(() => {
    // Permalink may target serverMessageId while the bubble still keys on client id.
    if (focus?.id !== message.id && focus?.id !== message.serverMessageId) {
      return;
    }
    ref.current?.scrollIntoView({ behavior: "smooth", block: "center" });
  }, [focus?.id, focus?.nonce, message.id, message.serverMessageId]);

  if (isExecutionHarvestMessage(message)) {
    return (
      <div
        ref={ref}
        className="scroll-mt-6 rounded-xl animate-message-enter motion-reduce:animate-none"
      >
        <HarvestSystemChip message={message} />
      </div>
    );
  }

  return (
    <div
      ref={ref}
      className="scroll-mt-6 rounded-xl animate-message-enter motion-reduce:animate-none"
    >
      {message.role === "user" ? (
        <UserMessage message={message} />
      ) : (
        <AssistantMessage message={message} />
      )}
    </div>
  );
});

export type { MessageBubbleProps } from "./types";
