import type { Message } from "@/stores/conversation";
import { describe, expect, it } from "vitest";
import {
  COMPOSER_CONTINUE_PLACEHOLDER,
  COMPOSER_EMPTY_INTERRUPTED_HINT,
  isContinuableAssistant,
  isEmptyInterruptedAssistant,
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

  it("exposes empty-interrupted light hint (再发=重试，无按钮)", () => {
    expect(COMPOSER_EMPTY_INTERRUPTED_HINT).toMatch(/发送下一条/);
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

  it("detects empty interrupted for layer-1 light hint", () => {
    expect(
      isEmptyInterruptedAssistant(
        msg({ finishReason: "interrupted", content: "" }),
      ),
    ).toBe(true);
    expect(
      isEmptyInterruptedAssistant(msg({ finishReason: "interrupted" })),
    ).toBe(false);
    expect(
      isEmptyInterruptedAssistant(
        msg({ finishReason: "cancelled", content: "" }),
      ),
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
