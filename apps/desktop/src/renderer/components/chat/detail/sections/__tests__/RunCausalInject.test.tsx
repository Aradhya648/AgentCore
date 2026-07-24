// @vitest-environment jsdom

import { RunCausalInjectBlock } from "@/components/chat/detail/sections/RunCausalInject";
import type { AgentState, RunNode } from "@/stores/execution";
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

vi.mock("@/stores/disclosure", () => ({
  usePersistentDisclosure: (_key: string | null, initial: boolean) => {
    const { useState } = require("react");
    return useState(initial);
  },
}));

const runs = [
  {
    id: "r1",
    agentId: "w1",
    task: "调研竞品定价",
    status: "completed",
    dependsOn: [],
    parentRunId: null,
    continuesRunId: null,
    receivedContext: [],
    escalations: [],
    durationMs: 1000,
  },
  {
    id: "r2",
    agentId: "w2",
    task: "撰写定价建议",
    status: "completed",
    dependsOn: ["r1"],
    parentRunId: null,
    continuesRunId: null,
    receivedContext: [],
    escalations: [],
    durationMs: 1000,
  },
] as unknown as RunNode[];

const agent = (id: string, role: string): AgentState => ({
  id,
  role,
  thinking: true,
  status: "idle",
  currentRunId: null,
  outputChunks: [],
  reasoningChunks: [],
  toolCalls: [],
  toolProgress: null,
  toolExecutionLive: null,
});

const agents: AgentState[] = [agent("w1", "研究员"), agent("w2", "撰写员")];

describe("RunCausalInjectBlock", () => {
  it("renders nothing without inject in-edges", () => {
    const { container } = render(
      <RunCausalInjectBlock
        runId="r1"
        graph={{ nodes: [], edges: [] }}
        runs={runs}
        agents={agents}
        onSelect={vi.fn()}
        sceneKey="test"
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("shows collapsed summary by default", () => {
    render(
      <RunCausalInjectBlock
        runId="r2"
        graph={{
          nodes: [
            { run_id: "r1", role: "研究员" },
            { run_id: "r2", role: "撰写员" },
          ],
          edges: [{ kind: "inject", from: "r1", to: "r2" }],
        }}
        runs={runs}
        agents={agents}
        onSelect={vi.fn()}
        sceneKey="test"
      />,
    );
    expect(screen.getByText("数据从哪来")).toBeTruthy();
    expect(screen.getByText("研究员 → 本 run")).toBeTruthy();
    expect(screen.queryByText("调研竞品定价")).toBeNull();
  });

  it("expands inject rows and drills into source run", () => {
    const onSelect = vi.fn();
    render(
      <RunCausalInjectBlock
        runId="r2"
        graph={{
          nodes: [
            { run_id: "r1", role: "研究员" },
            { run_id: "r2", role: "撰写员" },
          ],
          edges: [{ kind: "inject", from: "r1", to: "r2" }],
        }}
        runs={runs}
        agents={agents}
        onSelect={onSelect}
        sceneKey="test"
      />,
    );
    fireEvent.click(screen.getByText("数据从哪来"));
    expect(screen.getByText("调研竞品定价")).toBeTruthy();
    fireEvent.click(screen.getByText("研究员"));
    expect(onSelect).toHaveBeenCalledWith("r1", "研究员");
  });
});
