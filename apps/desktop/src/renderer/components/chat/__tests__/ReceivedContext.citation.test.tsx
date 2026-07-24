// @vitest-environment jsdom

import { ContextBlockCard } from "@/components/chat/ReceivedContext";
import type { ContextBlockWire } from "@/types/events";
import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/stores/disclosure", () => ({
  usePersistentDisclosure: (_key: string | null, initial: boolean) =>
    useState(initial),
}));

vi.mock("@/components/prompt/PromptDocument", () => ({
  PromptDocument: ({ text }: { text: string }) => (
    <pre data-testid="prompt-body">{text}</pre>
  ),
}));

function block(
  overrides: Partial<ContextBlockWire> & Pick<ContextBlockWire, "channel">,
): ContextBlockWire {
  return {
    heading: "heading",
    body: "首行摘要\n完整正文第二行",
    chars: 20,
    truncated: false,
    files: [],
    source_role: "",
    source_run_id: "",
    fidelity: "",
    ...overrides,
  };
}

describe("ContextBlockCard citation vs incremental", () => {
  it("copy-type dependency renders citation card with badges + summary", () => {
    const onNavigate = vi.fn();
    render(
      <ContextBlockCard
        block={block({
          channel: "dependency",
          source_role: "调研员",
          source_run_id: "run-up",
          fidelity: "summarize",
          truncated: true,
        })}
        defaultOpen={false}
        onNavigate={onNavigate}
      />,
    );

    expect(screen.getByText("前置结果")).toBeTruthy();
    expect(screen.getByText("来自 调研员")).toBeTruthy();
    expect(screen.getByText("摘要")).toBeTruthy();
    expect(screen.getByText("已截断")).toBeTruthy();
    expect(screen.getByText("首行摘要")).toBeTruthy();
    expect(screen.queryByTestId("prompt-body")).toBeNull();

    fireEvent.click(screen.getByText("来自 调研员"));
    expect(onNavigate).toHaveBeenCalledWith("run-up");

    fireEvent.click(screen.getByText("首行摘要"));
    expect(screen.getByTestId("prompt-body").textContent).toBe(
      "首行摘要\n完整正文第二行",
    );
  });

  it("incremental team_position keeps segment card (heading + peek)", () => {
    render(
      <ContextBlockCard
        block={block({
          channel: "team_position",
          heading: "你在团队中的位置",
          body: "你是撰写员，产出交给主编。",
        })}
        defaultOpen={false}
      />,
    );

    expect(screen.getByText("你在团队中的位置")).toBeTruthy();
    expect(screen.getByText("你是撰写员，产出交给主编。")).toBeTruthy();
    // Citation badges (fidelity etc.) stay absent on incremental cards when collapsed.
    expect(screen.queryByText("摘要")).toBeNull();
  });

  it("presentation=incremental forces segment card even for copy channels", () => {
    render(
      <ContextBlockCard
        block={block({
          channel: "opponent",
          heading: "上轮陈词摘录",
          body: "对方说我们错了。",
          source_role: "正方",
          fidelity: "pass_through",
        })}
        defaultOpen={false}
        presentation="incremental"
      />,
    );

    expect(screen.getByText("上轮陈词摘录")).toBeTruthy();
    // Incremental collapsed: provenance badges are not on the header row.
    expect(screen.queryByText("全文")).toBeNull();
    expect(screen.getByText("对方说我们错了。")).toBeTruthy();
  });

  it("source without run id degrades to a plain badge", () => {
    const onNavigate = vi.fn();
    render(
      <ContextBlockCard
        block={block({
          channel: "history",
          source_role: "用户",
          source_run_id: "",
          body: "用户：你好\nCEO：您好",
        })}
        defaultOpen={false}
        onNavigate={onNavigate}
      />,
    );

    expect(screen.getByText("来自 用户")).toBeTruthy();
    fireEvent.click(screen.getByText("来自 用户"));
    expect(onNavigate).not.toHaveBeenCalled();
  });
});
