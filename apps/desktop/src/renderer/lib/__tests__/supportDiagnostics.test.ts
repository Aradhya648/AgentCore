import { describe, expect, it } from "vitest";
import { formatSupportDiagnosticText } from "../supportDiagnostics";

describe("formatSupportDiagnosticText", () => {
  it("joins present ids and prefers --trace log command", () => {
    const trace = "t".repeat(32);
    expect(
      formatSupportDiagnosticText({
        conversationId: "conv-1",
        messageId: "msg-1",
        traceId: trace,
        executionId: "exec-1",
      }),
    ).toBe(
      [
        "conversation_id: conv-1",
        "message_id: msg-1",
        `trace_id: ${trace}`,
        "execution_id: exec-1",
        `uv run python scripts/log_timeline.py --trace ${trace}`,
      ].join("\n"),
    );
  });

  it("falls back to conversation_id log command when no trace", () => {
    expect(
      formatSupportDiagnosticText({
        conversationId: "conv-1",
        messageId: "msg-1",
        executionId: "exec-1",
      }),
    ).toBe(
      [
        "conversation_id: conv-1",
        "message_id: msg-1",
        "execution_id: exec-1",
        "uv run python scripts/log_timeline.py conv-1",
      ].join("\n"),
    );
  });

  it("omits optional ids and log command when nothing to query", () => {
    expect(
      formatSupportDiagnosticText({
        messageId: "msg-1",
        traceId: null,
        executionId: "  ",
      }),
    ).toBe("message_id: msg-1");
  });

  it("returns empty string when nothing to copy", () => {
    expect(formatSupportDiagnosticText({})).toBe("");
  });
});
