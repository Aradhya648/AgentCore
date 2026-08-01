// @vitest-environment jsdom
/**
 * Conversation replay chat-layout pins:
 * - user/assistant bubbles + process tool summary
 * - inline team graph click → onSelectRun (dock opens via parent)
 * - worker prose stays out of the timeline (in dock, not ProcessNode bodies)
 */
import { ChatTimeline } from "@/components/conversation-replay/ChatTimeline";
import { InspectorPanel } from "@/components/conversation-replay/InspectorPanel";
import type {
  ReplayMessage,
  ReplayRun,
  ReplaySpan,
} from "@/services/adminObservability";
import {
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

afterEach(() => {
  cleanup();
  vi.clearAllMocks();
});

function span(p: Partial<ReplaySpan> & { kind: string }): ReplaySpan {
  return {
    args_preview: null,
    finish_reason: null,
    input_tokens: null,
    name: null,
    output_tokens: null,
    result_preview: null,
    round_idx: null,
    run_id: null,
    success: true,
    ...p,
  };
}

function run(p: Partial<ReplayRun> & { run_id: string }): ReplayRun {
  return {
    agent_id: p.agent_id ?? p.run_id,
    content: null,
    debrief: null,
    depends_on: [],
    error: null,
    kind: "agent",
    output_summary: null,
    parent_run_id: null,
    role: null,
    status: "completed",
    task: "",
    ...p,
  };
}

function msg(p: Partial<ReplayMessage> & { id: string; role: string }): ReplayMessage {
  return {
    content: null,
    cost_total: 0,
    created_at: "2026-08-01T00:00:00Z",
    credential_source: null,
    metrics: null,
    models: [],
    runs: [],
    spans: [],
    trace_id: null,
    ...p,
  };
}

describe("ChatTimeline chat layout", () => {
  it("renders user bubble and assistant process + final body", () => {
    const messages: ReplayMessage[] = [
      msg({ id: "u1", role: "user", content: "帮我查一下" }),
      msg({
        id: "a1",
        role: "assistant",
        content: "查完了，结论如下。",
        spans: [
          span({
            kind: "tool",
            name: "web_search",
            args_preview: "q=foo",
            result_preview: "3 hits",
            success: true,
          }),
          span({
            kind: "llm",
            round_idx: 0,
            finish_reason: "stop",
            input_tokens: 10,
            output_tokens: 20,
          }),
        ],
      }),
    ];

    render(
      <ChatTimeline
        messages={messages}
        selectedId="a1"
        selectedRunId={null}
        onSelect={vi.fn()}
        onSelectRun={vi.fn()}
        isAnchored={() => false}
      />,
    );

    expect(screen.getByText("帮我查一下")).toBeTruthy();
    expect(screen.getByText("查完了，结论如下。")).toBeTruthy();
    expect(screen.getByText("1 次模型调用 · 1 次工具")).toBeTruthy();
    // Collapsed by default — tool name not visible until expand
    expect(screen.queryByText("web_search")).toBeNull();
  });

  it("does not dump worker body into the timeline; graph click selects run", () => {
    const onSelectRun = vi.fn();
    const workerBody = "队员私有长文不应出现在主栏";
    const messages: ReplayMessage[] = [
      msg({
        id: "a1",
        role: "assistant",
        content: "CEO 汇总",
        runs: [
          run({
            run_id: "r-worker",
            role: "研究员",
            task: "搜集资料",
            content: workerBody,
            status: "completed",
          }),
        ],
      }),
    ];

    render(
      <ChatTimeline
        messages={messages}
        selectedId="a1"
        selectedRunId={null}
        onSelect={vi.fn()}
        onSelectRun={onSelectRun}
        isAnchored={() => false}
      />,
    );

    expect(screen.getByText("CEO 汇总")).toBeTruthy();
    expect(screen.getByText("协作 · 1 队员")).toBeTruthy();
    expect(screen.queryByText(workerBody)).toBeNull();

    fireEvent.click(screen.getByText("研究员"));
    expect(onSelectRun).toHaveBeenCalledWith("r-worker");
  });
});

describe("InspectorPanel worker dock", () => {
  it("shows worker content and can clear selection", () => {
    const onClearRun = vi.fn();
    const message = msg({
      id: "a1",
      role: "assistant",
      content: "CEO",
      runs: [
        run({
          run_id: "r1",
          role: "写手",
          task: "起草",
          content: "队员正文在此",
        }),
      ],
      spans: [
        span({
          kind: "tool",
          name: "file_read",
          run_id: "r1",
          result_preview: "ok",
        }),
      ],
    });

    render(
      <InspectorPanel
        message={message}
        selectedRunId="r1"
        onSelectRun={vi.fn()}
        onClearRun={onClearRun}
        onClose={vi.fn()}
        cnyLabel="¥0.01"
      />,
    );

    expect(screen.getByText("队员正文在此")).toBeTruthy();
    expect(screen.getByText("起草")).toBeTruthy();
    fireEvent.click(screen.getByText("返回列表"));
    expect(onClearRun).toHaveBeenCalled();
  });

  it("shows worker list without tabs when nothing selected", () => {
    const message = msg({
      id: "a1",
      role: "assistant",
      content: "CEO",
      runs: [run({ run_id: "r1", role: "写手" })],
    });

    render(
      <InspectorPanel
        message={message}
        selectedRunId={null}
        onSelectRun={vi.fn()}
        onClearRun={vi.fn()}
        onClose={vi.fn()}
      />,
    );

    expect(screen.queryByText("运维")).toBeNull();
    expect(screen.queryByText("执行")).toBeNull();
    expect(screen.queryByText("检视")).toBeNull();
    expect(screen.getByText("写手")).toBeTruthy();
  });
});
