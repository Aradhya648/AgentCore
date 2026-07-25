import type { Message } from "@/stores/conversation";
import { describe, expect, it } from "vitest";
import {
  COMPOSER_CONTINUE_PLACEHOLDER,
  isContinuableAssistant,
} from "../composerContinueHint";

function msg(
  partial: Partial<Message> & Pick<Message, "finishReason">,
): Message {
  return {
    id: "a1",
    role: "assistant",
    content: "hello",
    createdAt: new Date().toISOString(),
    executionId: null,
    isStreaming: false,
    ...partial,
  };
}

describe("composerContinueHint", () => {
  it("exposes the continue placeholder copy", () => {
    expect(COMPOSER_CONTINUE_PLACEHOLDER).toContain("继续");
  });

  it("marks cancelled / interrupted-with-body / max_rounds as continuable", () => {
    expect(isContinuableAssistant(msg({ finishReason: "cancelled" }))).toBe(
      true,
    );
    expect(isContinuableAssistant(msg({ finishReason: "interrupted" }))).toBe(
      true,
    );
    expect(isContinuableAssistant(msg({ finishReason: "max_rounds" }))).toBe(
      true,
    );
  });

  it("rejects empty interrupted (no composer continue; re-ask via new turn)", () => {
    expect(
      isContinuableAssistant(msg({ finishReason: "interrupted", content: "" })),
    ).toBe(false);
  });

  it("rejects streaming / end_turn / non-assistant", () => {
    expect(isContinuableAssistant(msg({ finishReason: "end_turn" }))).toBe(
      false,
    );
    expect(
      isContinuableAssistant(
        msg({ finishReason: "cancelled", isStreaming: true }),
      ),
    ).toBe(false);
    expect(
      isContinuableAssistant({
        ...msg({ finishReason: "cancelled" }),
        role: "user",
      }),
    ).toBe(false);
  });
});
