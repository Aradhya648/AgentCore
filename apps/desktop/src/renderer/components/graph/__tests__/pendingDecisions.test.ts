import type { Execution, RunNode } from "@/stores/execution";
import { describe, expect, it } from "vitest";
import {
  type PendingInteractionRef,
  collectGraphPendingDecisions,
} from "../pendingDecisions";

function run(partial: Partial<RunNode> & { id: string }): RunNode {
  return {
    agentId: partial.id,
    task: "",
    status: "running",
    dependsOn: [],
    outputSummary: null,
    outputFiles: [],
    debrief: null,
    durationMs: null,
    startedAt: null,
    error: null,
    failureKind: null,
    productLanded: null,
    parentRunId: null,
    kind: "agent",
    role: null,
    model: null,
    usage: null,
    cost: null,
    stance: null,
    group: null,
    round: 0,
    sideKey: null,
    continuesRunId: null,
    continuationIndex: 0,
    revised: null,
    replacesRunId: null,
    actId: "act-1",
    checkpoint: null,
    receivedContext: [],
    escalations: [],
    process: [],
    ...partial,
  } as RunNode;
}

function execution(runs: RunNode[], agents: { id: string; role: string }[]) {
  return {
    id: "exec1",
    planType: "multi_agent",
    taskSummary: "T",
    status: "running",
    agents: agents.map((a) => ({ ...a })),
    runs,
    acts: [],
  } as unknown as Execution;
}

describe("collectGraphPendingDecisions", () => {
  it("returns [] with no execution", () => {
    expect(collectGraphPendingDecisions(null)).toEqual([]);
    expect(collectGraphPendingDecisions(undefined)).toEqual([]);
  });

  it("collects pending escalations anchored to their run + act, with role label", () => {
    const exec = execution(
      [
        run({
          id: "r1",
          actId: "act-2",
          escalations: [
            {
              id: "e1",
              question: "q",
              assumption: "a",
              blocking: true,
              status: "pending",
              answer: null,
              kind: "dep",
              questions: [],
            },
          ],
        }),
      ],
      [{ id: "r1", role: "调研" }],
    );
    const out = collectGraphPendingDecisions(exec);
    expect(out).toEqual([
      {
        id: "esc:e1",
        kind: "escalation",
        runId: "r1",
        actId: "act-2",
        title: "调研",
        detail: "待你拍板（缺输入）",
      },
    ]);
  });

  it("collects pending checkpoints and ignores resolved escalations/checkpoints", () => {
    const exec = execution(
      [
        run({
          id: "r1",
          checkpoint: { status: "pending", decision: null },
          escalations: [
            {
              id: "e0",
              question: "q",
              assumption: "a",
              blocking: false,
              status: "resolved",
              answer: "ok",
              kind: "normal",
              questions: [],
            },
          ],
        }),
        run({
          id: "r2",
          checkpoint: { status: "resolved", decision: "continue" },
        }),
      ],
      [{ id: "r1", role: "撰写" }],
    );
    const out = collectGraphPendingDecisions(exec);
    expect(out).toEqual([
      {
        id: "cp:r1",
        kind: "checkpoint",
        runId: "r1",
        actId: "act-1",
        title: "撰写",
        detail: "待放行",
      },
    ]);
  });

  it("excludes the captain run from node-anchored decisions", () => {
    const exec = execution(
      [
        run({
          id: "cap",
          kind: "captain",
          checkpoint: { status: "pending", decision: null },
        }),
        run({ id: "r1", checkpoint: { status: "pending", decision: null } }),
      ],
      [{ id: "r1", role: "撰写" }],
    );
    const out = collectGraphPendingDecisions(exec);
    expect(out.map((d) => d.runId)).toEqual(["r1"]);
  });

  it("anchors delegation authorization to the first worker run", () => {
    const exec = execution(
      [run({ id: "r1", status: "pending", actId: "act-1" })],
      [{ id: "r1", role: "调研" }],
    );
    const interactions: PendingInteractionRef[] = [
      { kind: "delegation_authorization", id: "auth1" },
    ];
    const out = collectGraphPendingDecisions(exec, interactions);
    expect(out).toEqual([
      {
        id: "auth:auth1",
        kind: "delegation_authorization",
        runId: "r1",
        actId: "act-1",
        title: "团队授权",
        detail: "放行开工",
      },
    ]);
  });

  it("anchors tool approval to the captain (or null when absent)", () => {
    const withCaptain = execution(
      [run({ id: "cap", kind: "captain" }), run({ id: "r1" })],
      [],
    );
    expect(
      collectGraphPendingDecisions(withCaptain, [
        { kind: "approval", id: "tc1" },
      ]),
    ).toEqual([
      {
        id: "appr:tc1",
        kind: "approval",
        runId: "cap",
        actId: null,
        title: "工具审批",
        detail: "待放行",
      },
    ]);
  });

  it("orders node-anchored decisions before execution-level ones", () => {
    const exec = execution(
      [
        run({
          id: "r1",
          escalations: [
            {
              id: "e1",
              question: "q",
              assumption: "a",
              blocking: true,
              status: "pending",
              answer: null,
              kind: "normal",
              questions: [],
            },
          ],
        }),
      ],
      [{ id: "r1", role: "调研" }],
    );
    const out = collectGraphPendingDecisions(exec, [
      { kind: "delegation_authorization", id: "auth1" },
    ]);
    expect(out.map((d) => d.kind)).toEqual([
      "escalation",
      "delegation_authorization",
    ]);
  });
});
