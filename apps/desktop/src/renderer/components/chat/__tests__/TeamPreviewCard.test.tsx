// @vitest-environment jsdom
/**
 * 开工卡被动记录：默认一行结论收起，点开才看队员明细；
 * resolved / pending 摘要文案与各 decision label 对齐。
 */

import { conversationKeys } from "@/lib/queryKeys";
import type { TeamPreviewDisplay } from "@/stores/conversation";
import { type ExecutionPlan, useExecutionStore } from "@/stores/execution";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  type RenderResult,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { GraphTeamPreview, TeamPreviewCard } from "../TeamPreviewCard";

vi.mock("@/stores/disclosure", () => ({
  usePersistentDisclosure: (_key: string | null, initial: boolean) => {
    const { useState } = require("react");
    return useState(initial);
  },
}));

function makePreview(
  overrides: Partial<TeamPreviewDisplay> = {},
): TeamPreviewDisplay {
  return {
    id: "tp-1",
    primitive: "delegate",
    workers: [
      {
        run_id: "r1",
        role: "研究员",
        task: "调研竞品定价策略与公开资料",
        depends_on: [],
        debate: false,
      },
      {
        run_id: "r2",
        role: "撰写员",
        task: "基于调研写定价建议",
        depends_on: ["r1"],
        debate: true,
      },
    ],
    tools: [],
    motion: "",
    form: "",
    sides: [],
    maxRounds: 0,
    thorough: true,
    status: "resolved",
    decision: "continue",
    note: "",
    ...overrides,
  };
}

function renderCard(ui: ReactElement): RenderResult {
  const client = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Number.POSITIVE_INFINITY },
    },
  });
  client.setQueryData(conversationKeys.grouped, {
    folders: [],
    conversations: [],
  });
  return render(
    <QueryClientProvider client={client}>{ui}</QueryClientProvider>,
  );
}

const MID = "msg-tp-debate-host";

const debatePlan: ExecutionPlan = {
  id: "exec-debate-host",
  planType: "multi_agent",
  taskSummary: "辩论",
  agents: [
    { id: "a", role: "正方" },
    { id: "b", role: "反方" },
  ],
  runs: [
    { id: "r1", agentId: "a", task: "立论", dependsOn: [] },
    { id: "r2", agentId: "b", task: "反驳", dependsOn: [] },
  ],
};

function makeDebatePreview(
  overrides: Partial<TeamPreviewDisplay> = {},
): TeamPreviewDisplay {
  return makePreview({
    primitive: "debate",
    workers: [],
    motion: "该不该上四天工作制？",
    form: "debate",
    sides: [
      { key: "pro", name: "正方", stance: "应推广" },
      { key: "con", name: "反方", stance: "暂缓" },
    ],
    maxRounds: 5,
    thorough: true,
    status: "resolved",
    decision: "continue",
    note: "",
    ...overrides,
  });
}

afterEach(() => {
  cleanup();
  useExecutionStore.setState({ byId: {} });
  vi.restoreAllMocks();
});

describe("TeamPreviewCard", () => {
  it("resolved 默认收起为一行结论，不含队员任务全文", () => {
    renderCard(<TeamPreviewCard preview={makePreview()} />);

    const toggle = screen.getByRole("button", {
      name: /已授权开工 · 首波已放行 · 2 名队员/,
    });
    expect(toggle.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("研究员")).toBeNull();
    expect(screen.queryByText("调研竞品定价策略与公开资料")).toBeNull();
  });

  it("点击展开后显示队员角色、任务、依赖与辩论标记", () => {
    renderCard(<TeamPreviewCard preview={makePreview()} />);

    fireEvent.click(
      screen.getByRole("button", {
        name: /已授权开工 · 首波已放行 · 2 名队员/,
      }),
    );

    expect(
      screen
        .getByRole("button", {
          name: /已授权开工 · 首波已放行 · 2 名队员/,
        })
        .getAttribute("aria-expanded"),
    ).toBe("true");
    expect(screen.getByText("研究员")).toBeTruthy();
    expect(screen.getByText("撰写员")).toBeTruthy();
    expect(screen.getByText("调研竞品定价策略与公开资料")).toBeTruthy();
    expect(screen.getByText("基于调研写定价建议")).toBeTruthy();
    expect(screen.getByText("依赖 1 步")).toBeTruthy();
    expect(screen.getByText("辩论")).toBeTruthy();
  });

  it("resolved 展开后显示备注 note", () => {
    renderCard(
      <TeamPreviewCard
        preview={makePreview({ note: "先做公开竞品，不做内部访谈" })}
      />,
    );

    fireEvent.click(
      screen.getByRole("button", {
        name: /已授权开工 · 嘱咐已注入队员 · 2 名队员/,
      }),
    );
    expect(screen.getByText("先做公开竞品，不做内部访谈")).toBeTruthy();
  });

  it("pending 降级为单行拍板标记，无明细、无任何按钮（方案 C）", () => {
    renderCard(
      <TeamPreviewCard
        preview={makePreview({ status: "pending", decision: null })}
      />,
    );

    const marker = screen.getByTestId("pending-decision-marker");
    expect(marker.textContent).toContain(
      "等你确认 · 确认后才会开工（2 名队员）",
    );
    expect(marker.textContent).toContain("入口在下方拍板卡");
    // 单行标记：完整分工表归 ResumePrompt 拍板中心，这里零展开、零操作。
    expect(screen.queryByText("研究员")).toBeNull();
    expect(screen.queryByText("调研竞品定价策略与公开资料")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it.each([
    ["adjust", "已调整 · 备注已注入队员并开做 · 2 名队员"],
    ["stop", "已停止 · 团队未启动 · 2 名队员"],
    ["timeout", "未及时回应，已自动开做 · 2 名队员"],
    ["orphaned", "已失效（回合已结束或服务已重启） · 2 名队员"],
  ] as const)("resolved decision=%s 保留既有 label 文案", (decision, label) => {
    renderCard(<TeamPreviewCard preview={makePreview({ decision })} />);
    expect(screen.getByRole("button", { name: label })).toBeTruthy();
  });

  it("debate resolved research_first 显示已选先调研文案", () => {
    renderCard(
      <TeamPreviewCard
        preview={makeDebatePreview({ decision: "research_first" })}
      />,
    );
    expect(
      screen.getByRole("button", {
        name: /已选先调研 · 辩论未开赛/,
      }),
    ).toBeTruthy();
  });

  it("resolved continue + note 显示嘱咐已注入", () => {
    renderCard(
      <TeamPreviewCard
        preview={makePreview({
          decision: "continue",
          note: "先做公开竞品",
        })}
      />,
    );
    expect(
      screen.getByRole("button", {
        name: /已授权开工 · 嘱咐已注入队员 · 2 名队员/,
      }),
    ).toBeTruthy();
  });

  it("debate resolved continue + note 显示嘱咐已注入", () => {
    renderCard(
      <TeamPreviewCard
        preview={makePreview({
          primitive: "debate",
          workers: [],
          decision: "continue",
          note: "最关心成本谁买单",
          motion: "该不该上四天工作制？",
          form: "debate",
          sides: [
            { key: "pro", name: "正方", stance: "应推广" },
            { key: "con", name: "反方", stance: "暂缓" },
          ],
          maxRounds: 5,
          thorough: true,
        })}
      />,
    );
    expect(
      screen.getByRole("button", {
        name: /已授权开赛 · 嘱咐已注入 · 2 方/,
      }),
    ).toBeTruthy();
  });

  it("debate 历史 adjust 仍渲染「已调整辩题」", () => {
    renderCard(
      <TeamPreviewCard
        preview={makePreview({
          primitive: "debate",
          workers: [],
          decision: "adjust",
          note: "旧路径改辩题",
          motion: "原辩题",
          form: "debate",
          sides: [
            { key: "pro", name: "正方", stance: "应推广" },
            { key: "con", name: "反方", stance: "暂缓" },
          ],
          maxRounds: 5,
          thorough: true,
        })}
      />,
    );
    expect(
      screen.getByRole("button", {
        name: /已调整辩题 · 开赛 · 2 方/,
      }),
    ).toBeTruthy();
  });

  it("debate pending 同样降级为单行拍板标记（辩题立场归拍板中心）", () => {
    renderCard(
      <TeamPreviewCard
        preview={makePreview({
          primitive: "debate",
          workers: [],
          status: "pending",
          decision: null,
          motion: "该不该上四天工作制？",
          form: "debate",
          sides: [
            { key: "pro", name: "正方", stance: "应推广" },
            { key: "con", name: "反方", stance: "暂缓" },
          ],
          maxRounds: 5,
          thorough: true,
        })}
      />,
    );

    const marker = screen.getByTestId("pending-decision-marker");
    expect(marker.textContent).toContain("等你确认 · 确认后才会开赛（2 方）");
    expect(screen.queryByText("该不该上四天工作制？")).toBeNull();
    expect(screen.queryByText("正方")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("debate resolved 但协作图未出现时独立卡仍兜底显示", () => {
    useExecutionStore.getState().startExecution(debatePlan, MID);
    // No run_started → all pending → teamHasStartedRuns false
    renderCard(
      <TeamPreviewCard preview={makeDebatePreview()} messageId={MID} />,
    );
    expect(
      screen.getByRole("button", {
        name: /已授权开赛 · 辩论已放行 · 2 方/,
      }),
    ).toBeTruthy();
  });

  it("debate resolved + 协作图已出现时独立卡隐藏", () => {
    useExecutionStore.getState().startExecution(debatePlan, MID);
    useExecutionStore.getState().recordFrame(
      {
        t: 1,
        kind: "run_started",
        runId: "r1",
        agentId: "a",
        parentRunId: null,
        runKind: "agent",
        continuesRunId: null,
      },
      MID,
    );
    const { container } = renderCard(
      <TeamPreviewCard preview={makeDebatePreview()} messageId={MID} />,
    );
    expect(container.textContent).toBe("");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("delegate resolved + 协作图已出现时独立卡隐藏", () => {
    useExecutionStore.getState().startExecution(debatePlan, MID);
    useExecutionStore.getState().recordFrame(
      {
        t: 1,
        kind: "run_started",
        runId: "r1",
        agentId: "a",
        parentRunId: null,
        runKind: "agent",
        continuesRunId: null,
      },
      MID,
    );
    const { container } = renderCard(
      <TeamPreviewCard preview={makePreview()} messageId={MID} />,
    );
    expect(container.textContent).toBe("");
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("delegate resolved 但协作图未出现时独立卡仍兜底显示", () => {
    useExecutionStore.getState().startExecution(debatePlan, MID);
    renderCard(<TeamPreviewCard preview={makePreview()} messageId={MID} />);
    expect(
      screen.getByRole("button", {
        name: /已授权开工 · 首波已放行 · 2 名队员/,
      }),
    ).toBeTruthy();
  });
});

describe("GraphTeamPreview", () => {
  it("debate：ghost 触发器默认关闭，点开 Popover 显示辩题/轮次/双方/嘱咐", () => {
    renderCard(
      <GraphTeamPreview
        preview={makeDebatePreview({ note: "最关心成本谁买单" })}
      />,
    );
    const trigger = screen.getByTestId("graph-team-preview");
    expect(trigger.textContent).toMatch(/辩题 · 2 方/);
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("该不该上四天工作制？")).toBeNull();

    fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("该不该上四天工作制？")).toBeTruthy();
    expect(screen.getByText(/认真辩透 · 上限 5 轮/)).toBeTruthy();
    expect(screen.getByText("正方")).toBeTruthy();
    expect(screen.getByText("应推广")).toBeTruthy();
    expect(screen.getByText("反方")).toBeTruthy();
    expect(screen.getByText("暂缓")).toBeTruthy();
    expect(screen.getByText("最关心成本谁买单")).toBeTruthy();
  });

  it("debate 开赛卡有模型字段时展示三方署名", () => {
    renderCard(
      <GraphTeamPreview
        preview={makeDebatePreview({
          sides: [
            {
              key: "pro",
              name: "正方",
              stance: "应推广",
              model: "doubao/seed-2.0",
              origin: "platform",
            },
            {
              key: "con",
              name: "反方",
              stance: "暂缓",
              model: "deepseek/deepseek-v4-flash",
              origin: "platform",
            },
          ],
          moderatorModel: "deepseek/deepseek-v4-pro",
          moderatorOrigin: "platform",
        })}
      />,
    );
    fireEvent.click(screen.getByTestId("graph-team-preview"));
    const line = screen.getByTestId("debate-roster-line");
    expect(line.textContent).toBe("正方 豆包 · 反方 DeepSeek · 裁判 DeepSeek");
  });

  it("debate 开赛卡无模型字段时不展示跨模型署名（同模型场零噪声）", () => {
    renderCard(<GraphTeamPreview preview={makeDebatePreview()} />);
    fireEvent.click(screen.getByTestId("graph-team-preview"));
    expect(screen.queryByTestId("debate-roster-line")).toBeNull();
    expect(screen.queryByText(/正方 豆包/)).toBeNull();
    expect(screen.getByText("正方")).toBeTruthy();
    expect(screen.getByText("反方")).toBeTruthy();
  });

  it("debate 开赛卡展示消歧候选列表", () => {
    renderCard(
      <GraphTeamPreview
        preview={makeDebatePreview({
          modelCandidates: [
            {
              model: "deepseek-chat",
              origin: "byok",
              provider_id: "ds",
              label: "DeepSeek Chat",
              side_key: "con",
            },
            {
              model: "deepseek-coder",
              origin: "byok",
              provider_id: "ds2",
              label: "DeepSeek Coder",
            },
          ],
        })}
      />,
    );
    fireEvent.click(screen.getByTestId("graph-team-preview"));
    const box = screen.getByTestId("debate-model-candidates");
    expect(box.textContent).toMatch(/消歧失败/);
    expect(box.textContent).toMatch(/DeepSeek Chat/);
    expect(box.textContent).toMatch(/byok\/deepseek-chat/);
  });

  it("delegate：ghost 触发器默认关闭，点开 Popover 显示队员分工/嘱咐", () => {
    renderCard(
      <GraphTeamPreview preview={makePreview({ note: "先出竞品对照表" })} />,
    );
    const trigger = screen.getByTestId("graph-team-preview");
    expect(trigger.textContent).toMatch(/分工 · 2 名队员/);
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
    expect(screen.queryByText("研究员")).toBeNull();

    fireEvent.click(trigger);
    expect(trigger.getAttribute("aria-expanded")).toBe("true");
    expect(screen.getByText("研究员")).toBeTruthy();
    expect(screen.getByText("调研竞品定价策略与公开资料")).toBeTruthy();
    expect(screen.getByText("撰写员")).toBeTruthy();
    expect(screen.getByText("基于调研写定价建议")).toBeTruthy();
    expect(screen.getByText("先出竞品对照表")).toBeTruthy();
  });
});
