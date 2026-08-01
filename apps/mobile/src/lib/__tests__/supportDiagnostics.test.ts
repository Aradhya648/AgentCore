import type { SSEEvent } from "@agentcore/contract-types";
import { describe, expect, it } from "vitest";
import {
  extractSupportIdsFromEvents,
  formatSupportDiagnosticText,
} from "../supportDiagnostics";

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
        "阅读这段产品AI日志：",
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
        "阅读这段产品AI日志：",
        "conversation_id: conv-1",
        "message_id: msg-1",
        "execution_id: exec-1",
        "uv run python scripts/log_timeline.py conv-1",
      ].join("\n"),
    );
  });

  it("returns empty string when nothing to copy", () => {
    expect(formatSupportDiagnosticText({})).toBe("");
  });
});

describe("extractSupportIdsFromEvents", () => {
  it("reads message_start + first run_plan ids", () => {
    const events = [
      {
        type: "message_start",
        timestamp: "t0",
        payload: {
          message_id: "m1",
          conversation_id: "c1",
          trace_id: "a".repeat(32),
        },
      },
      {
        type: "run_plan",
        timestamp: "t1",
        payload: { execution_id: "ex1" },
      },
    ] as SSEEvent[];
    expect(extractSupportIdsFromEvents(events)).toEqual({
      messageId: "m1",
      traceId: "a".repeat(32),
      executionId: "ex1",
    });
  });
});
