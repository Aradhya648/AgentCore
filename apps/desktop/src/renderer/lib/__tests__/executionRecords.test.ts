import type { Message } from "@/stores/conversation/types";
import type { RunFrame } from "@/stores/execution";
import { describe, expect, it } from "vitest";
import {
  deriveExecutionRecords,
  executionRecordSummary,
  outputFromDisplay,
  recordsFromProcess,
  resolveRecordOutput,
  runIdFromFrames,
} from "../executionRecords";
import { shouldShowTerminalTab } from "../processOutput";

describe("executionRecordSummary", () => {
  it("prefers purpose for code_execute", () => {
    expect(
      executionRecordSummary("code_execute", {
        purpose: "算斐波那契",
        language: "python",
        code: "print(1)",
      }),
    ).toBe("算斐波那契");
  });

  it("falls back to language · first code line", () => {
    expect(
      executionRecordSummary("code_execute", {
        language: "python",
        code: "print(42)\nprint(1)",
      }),
    ).toBe("python · print(42)");
  });

  it("uses test_run command from display", () => {
    expect(
      executionRecordSummary(
        "test_run",
        {},
        { command: "pnpm test", framework: "vitest" },
      ),
    ).toBe("pnpm test");
  });
});

describe("outputFromDisplay / resolveRecordOutput", () => {
  it("reads stdout/stderr/exit_code", () => {
    expect(
      outputFromDisplay({
        stdout: "ok\n",
        stderr: "warn\n",
        exit_code: 1,
      }),
    ).toEqual({ stdout: "ok\n", stderr: "warn\n", exitCode: 1 });
  });

  it("prefers live chunks while running", () => {
    const text = resolveRecordOutput(
      {
        id: "t1",
        toolName: "code_execute",
        summary: "python",
        agentRole: "助手",
        status: "running",
        messageId: "m1",
        stdout: "",
        stderr: "",
        exitCode: null,
        orderKey: 0,
      },
      "hello",
      "err",
    );
    expect(text).toBe("helloerr");
  });

  it("uses authoritative display when done", () => {
    const text = resolveRecordOutput(
      {
        id: "t1",
        toolName: "code_execute",
        summary: "python",
        agentRole: "助手",
        status: "success",
        messageId: "m1",
        stdout: "done\n",
        stderr: "",
        exitCode: 0,
        orderKey: 0,
      },
      "stale",
      "",
    );
    expect(text).toContain("done");
    expect(text).toContain("退出码 0");
    expect(text).not.toContain("stale");
  });
});

describe("recordsFromProcess", () => {
  it("keeps only code_execute / test_run tool steps", () => {
    const recs = recordsFromProcess(
      [
        {
          kind: "tool",
          id: "a",
          tool_name: "web_search",
          arguments: {},
          result: null,
          status: "success",
        },
        {
          kind: "tool",
          id: "b",
          tool_name: "code_execute",
          arguments: { language: "bash", code: "echo hi" },
          result: "ok",
          status: "success",
          display: {
            stdout: "hi\n",
            stderr: "",
            exit_code: 0,
            language: "bash",
          },
        },
        {
          kind: "tool",
          id: "c",
          tool_name: "test_run",
          arguments: {},
          result: null,
          status: "running",
        },
      ],
      "msg-1",
      0,
    );
    expect(recs.map((r) => r.id)).toEqual(["b", "c"]);
    expect(recs[0]?.exitCode).toBe(0);
    expect(recs[1]?.status).toBe("running");
  });
});

describe("runIdFromFrames", () => {
  it("returns worker run id from tool_use_start", () => {
    const frames: RunFrame[] = [
      {
        t: 1,
        kind: "tool_use_start",
        toolCallId: "tc1",
        toolName: "code_execute",
        arguments: {},
        runId: "run-w1",
      },
    ];
    expect(runIdFromFrames(frames, "tc1")).toBe("run-w1");
    expect(runIdFromFrames(frames, "missing")).toBeUndefined();
  });

  it("treats empty runId as absent", () => {
    const frames: RunFrame[] = [
      {
        t: 1,
        kind: "tool_use_start",
        toolCallId: "tc1",
        toolName: "code_execute",
        arguments: {},
        runId: "",
      },
    ];
    expect(runIdFromFrames(frames, "tc1")).toBeUndefined();
  });
});

describe("deriveExecutionRecords", () => {
  it("flattens process tools across assistant messages in order", () => {
    const messages: Message[] = [
      {
        id: "u1",
        role: "user",
        content: "hi",
        createdAt: "2026-01-01T00:00:00.000Z",
        executionId: null,
        isStreaming: false,
      },
      {
        id: "a1",
        role: "assistant",
        content: "",
        createdAt: "2026-01-01T00:00:01.000Z",
        executionId: null,
        isStreaming: false,
        process: [
          {
            kind: "tool",
            id: "t1",
            tool_name: "code_execute",
            arguments: { language: "python", code: "1" },
            result: null,
            status: "success",
            display: {
              stdout: "1",
              stderr: "",
              exit_code: 0,
              language: "python",
            },
          },
        ],
      },
      {
        id: "a2",
        role: "assistant",
        content: "",
        createdAt: "2026-01-01T00:00:02.000Z",
        serverMessageId: "srv-2",
        executionId: null,
        isStreaming: false,
        process: [
          {
            kind: "tool",
            id: "t2",
            tool_name: "test_run",
            arguments: {},
            result: null,
            status: "error",
            display: { stdout: "", stderr: "fail", exit_code: 1 },
          },
        ],
      },
    ];
    const recs = deriveExecutionRecords(messages, {});
    expect(recs.map((r) => r.id)).toEqual(["t1", "t2"]);
    expect(recs[0]?.messageId).toBe("a1");
    expect(recs[1]?.messageId).toBe("srv-2");
    expect(recs[1]?.status).toBe("error");
  });
});

describe("shouldShowTerminalTab (M2)", () => {
  it("shows for processes or execution records alone", () => {
    expect(shouldShowTerminalTab(0, 0)).toBe(false);
    expect(shouldShowTerminalTab(1, 0)).toBe(true);
    expect(shouldShowTerminalTab(0, 2)).toBe(true);
  });
});
