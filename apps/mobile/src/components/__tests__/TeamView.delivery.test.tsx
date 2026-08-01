// @vitest-environment jsdom
/**
 * 用户面第③步：TeamView 交付挂载闸——delivered/notes 静默；
 * partial/blocked 仅轻提示（无验收卡、无动作、无缺口明细）。对齐桌面 DeliveryStatusMount。
 */
import { TeamView } from "@/components/TeamView";
import type { DeliveryStatusPayload } from "@agentcore/contract-types";
import type {
  ProjectedAgent,
  ProjectedRun,
} from "@agentcore/protocol-conformance";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

afterEach(cleanup);

function makeAgent(
  p: Partial<ProjectedAgent> & { id: string; role: string },
): ProjectedAgent {
  return {
    thinking: false,
    status: "completed",
    currentRunId: null,
    output: "",
    reasoning: "",
    toolProgress: null,
    ...p,
  };
}

function makeRun(p: Partial<ProjectedRun> & { id: string }): ProjectedRun {
  return {
    agentId: "a1",
    task: "task",
    status: "completed",
    dependsOn: [],
    outputSummary: null,
    debrief: null,
    durationMs: null,
    error: null,
    parentRunId: null,
    kind: "agent",
    role: "队员",
    model: null,
    usage: null,
    cost: null,
    stance: null,
    group: null,
    round: 0,
    continuesRunId: null,
    revised: null,
    replacesRunId: null,
    checkpoint: null,
    receivedContext: [],
    escalations: [],
    process: [],
    actId: "act-1",
    ...p,
  };
}

const agents = [makeAgent({ id: "a1", role: "队员" })];
const runs = [makeRun({ id: "r1", agentId: "a1" })];

function payload(
  partial: Pick<DeliveryStatusPayload, "state" | "summary"> &
    Partial<DeliveryStatusPayload>,
): DeliveryStatusPayload {
  return {
    execution_id: "exec-1",
    delivered_files: [],
    gaps: [
      {
        role: "验收",
        description: "course.pptx 未生成（云端无执行环境）",
      },
    ],
    actions: [
      {
        kind: "bind_local_folder",
        description: "绑定本机执行环境后可继续生成产物。",
      },
    ],
    ...partial,
  };
}

function renderTeam(deliveryStatus: DeliveryStatusPayload) {
  return render(
    <TeamView
      agents={agents}
      runs={runs}
      progress={{ completed: 1, total: 1 }}
      status="completed"
      acts={[]}
      teamNotes={[]}
      evidenceLedger={[]}
      deliveryStatus={deliveryStatus}
    />,
  );
}

describe("TeamView · 交付轻提示", () => {
  it("delivered：不出现验收卡与轻提示", () => {
    renderTeam(
      payload({
        state: "delivered",
        summary: "已交付 2 个文件",
        delivered_files: ["a.md", "b.md"],
        gaps: [],
        actions: [],
      }),
    );
    expect(screen.queryByText("交付验收")).toBeNull();
    expect(screen.queryByTestId("delivery-shortfall-hint")).toBeNull();
  });

  it("notes：不出现验收卡与轻提示", () => {
    renderTeam(
      payload({
        state: "notes",
        summary: "已交付 1 个文件；另有 1 处备注",
        gaps: [
          {
            role: "分区",
            description: "交接说明不够完整",
            severity: "warning",
            reason: "degraded_handoff",
          },
        ],
        actions: [],
      }),
    );
    expect(screen.queryByText("交付验收")).toBeNull();
    expect(screen.queryByText("有备注")).toBeNull();
    expect(screen.queryByTestId("delivery-shortfall-hint")).toBeNull();
  });

  it("partial：仅一句轻提示，无动作与缺口明细", () => {
    renderTeam(
      payload({
        state: "partial",
        summary: "已交付 2 个文件；1 项缺口",
      }),
    );
    const hint = screen.getByTestId("delivery-shortfall-hint");
    expect(hint.textContent).toBe("已交付 2 个文件；1 项缺口");
    expect(screen.queryByText("交付验收")).toBeNull();
    expect(screen.queryByText("部分未满足")).toBeNull();
    expect(screen.queryByText(/course\.pptx 未生成/)).toBeNull();
    expect(screen.queryByText(/绑定本机执行环境/)).toBeNull();
    expect(screen.queryByText("团队可能重派")).toBeNull();
  });

  it("blocked：仅一句轻提示，无动作", () => {
    renderTeam(
      payload({
        state: "blocked",
        summary: "未能交付：1 项缺口",
        delivered_files: [],
        actions: [{ kind: "future_kind", description: "未来的提示行" }],
      }),
    );
    expect(screen.getByTestId("delivery-shortfall-hint").textContent).toBe(
      "未能交付：1 项缺口",
    );
    expect(screen.queryByText("交付验收")).toBeNull();
    expect(screen.queryByText("未满足")).toBeNull();
    expect(screen.queryByText("未来的提示行")).toBeNull();
    expect(screen.queryByText("团队可能重派")).toBeNull();
  });
});
