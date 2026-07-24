// @vitest-environment jsdom
// 完成条件卡（批次验收 / completion_criteria）：delivery_status 的缺口 / 待操作渲染契约。
import type { DeliveryStatusPayload } from "@/types/events";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { DeliveryStatusCard } from "../DeliveryStatusCard";

const {
  sendTurnMock,
  useConversationStoreMock,
  getStateMock,
  setValueMock,
  pickAndBindLocalFolderMock,
} = vi.hoisted(() => ({
  sendTurnMock: vi.fn(),
  useConversationStoreMock: vi.fn(),
  getStateMock: vi.fn(),
  setValueMock: vi.fn(),
  pickAndBindLocalFolderMock: vi.fn(),
}));

vi.mock("@/services/turns", () => ({
  sendTurn: (...args: unknown[]) => sendTurnMock(...args),
}));

vi.mock("@/lib/bindLocalFolder", async () => {
  const actual = await vi.importActual<typeof import("@/lib/bindLocalFolder")>(
    "@/lib/bindLocalFolder",
  );
  return {
    ...actual,
    pickAndBindLocalFolder: (...args: unknown[]) =>
      pickAndBindLocalFolderMock(...args),
  };
});

vi.mock("@/stores/conversation", () => ({
  useConversationStore: Object.assign(
    (sel: (s: unknown) => unknown) => useConversationStoreMock(sel),
    { getState: () => getStateMock() },
  ),
}));

vi.mock("@/stores/composer", () => ({
  useComposerDraftStore: {
    getState: () => ({ setValue: setValueMock }),
  },
}));

// 折叠开合替身：用会话内 useState 取代持久化 hook（隔离 conversation store / localStorage），
// 让「点头部收起/展开」在测试里真正切换（对齐 FileArtifactsCard.test 的 disclosure mock）。
vi.mock("@/stores/disclosure", async () => {
  const { useState } = await import("react");
  return {
    usePersistentDisclosure: (_key: string | null, initial: boolean) =>
      useState(initial),
  };
});

beforeEach(() => {
  sendTurnMock.mockReset();
  useConversationStoreMock.mockReset();
  getStateMock.mockReset();
  setValueMock.mockReset();
  pickAndBindLocalFolderMock.mockReset();
  useConversationStoreMock.mockImplementation((sel: (s: unknown) => unknown) =>
    sel({ byId: { c1: { isGenerating: false } } }),
  );
  getStateMock.mockReturnValue({ addMessage: vi.fn() });
  sendTurnMock.mockResolvedValue(undefined);
});

afterEach(() => {
  cleanup();
});

const partial: DeliveryStatusPayload = {
  execution_id: "exec-1",
  state: "partial",
  summary: "已交付 2 个文件；1 项缺口",
  delivered_files: ["build_pptx.py", "讲稿.md"],
  gaps: [
    {
      role: "课件工程师",
      description: "course.pptx 未生成（云端无执行环境，脚本未运行）",
    },
  ],
  actions: [
    {
      kind: "bind_local_folder",
      description: "绑定本地文件夹后，团队可在你的电脑上运行脚本生成产物。",
    },
  ],
};

describe("DeliveryStatusCard", () => {
  it("renders partial state with gaps and bind action button", () => {
    render(<DeliveryStatusCard status={partial} conversationId="c1" />);
    expect(screen.getByText("完成条件")).toBeTruthy();
    expect(screen.getByText("部分未满足")).toBeTruthy();
    expect(screen.getByText("团队可能重派")).toBeTruthy();
    expect(screen.getByText("已交付 2 个文件；1 项缺口")).toBeTruthy();
    // 缺口仅由完成条件卡的明细行披露一次（无独立摘要行）。
    expect(screen.getByText(/course\.pptx 未生成/)).toBeTruthy();
    expect(screen.queryByTestId("delivery-gaps-lead")).toBeNull();
    // 已知 bind_local_folder 行动项 → 真按钮（复用 ask_user 卡的绑定通路）。
    expect(screen.getByRole("button", { name: "绑定本地文件夹" })).toBeTruthy();
  });

  it("renders blocked state and treats unknown action kinds as plain hints", () => {
    render(
      <DeliveryStatusCard
        status={{
          execution_id: "exec-2",
          state: "blocked",
          summary: "未能交付：1 项缺口",
          delivered_files: [],
          gaps: [
            { role: "验收", description: "尚无 worker 成功运行 code_execute" },
          ],
          actions: [{ kind: "future_kind", description: "未来的提示行" }],
        }}
        conversationId="c1"
      />,
    );
    expect(screen.getByText("未满足")).toBeTruthy();
    expect(screen.getByText("团队可能重派")).toBeTruthy();
    expect(screen.getByText("未来的提示行")).toBeTruthy();
    // 未知 kind 不渲染绑定按钮（向前兼容：按普通提示行呈现）——头部折叠按钮不算行动项。
    expect(screen.queryByRole("button", { name: "绑定本地文件夹" })).toBeNull();
  });

  it("renders nothing for delivered state (清单由产出文件卡承载)", () => {
    const { container } = render(
      <DeliveryStatusCard
        status={{
          execution_id: "exec-3",
          state: "delivered",
          summary: "已交付 2 个文件",
          delivered_files: ["a.md", "b.md"],
          gaps: [],
          actions: [],
        }}
        conversationId="c1"
      />,
    );
    expect(container.firstChild).toBeNull();
  });

  it("hides bind button without a conversation id (预览/离线回放)", () => {
    render(<DeliveryStatusCard status={partial} conversationId={null} />);
    // 无对话 id 不出绑定按钮；头部折叠按钮仍在（不是行动项）。
    expect(screen.queryByRole("button", { name: "绑定本地文件夹" })).toBeNull();
  });

  it("默认展开；点头部收起 gap 明细与 actions（头部仍可见），再点恢复", () => {
    render(<DeliveryStatusCard status={partial} conversationId="c1" />);
    // 默认展开：gap 明细 + 绑定行动项可见。
    expect(screen.getByText(/course\.pptx 未生成/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "绑定本地文件夹" })).toBeTruthy();

    // 整行头部即折叠开关。
    const header = screen.getByRole("button", { name: /完成条件/ });
    fireEvent.click(header);

    // 收起：gap 明细与 actions 区消失，头部（标题 + 状态徽标 + 团队可能重派）仍在。
    expect(screen.queryByText(/course\.pptx 未生成/)).toBeNull();
    expect(screen.queryByRole("button", { name: "绑定本地文件夹" })).toBeNull();
    expect(screen.getByText("完成条件")).toBeTruthy();
    expect(screen.getByText("部分未满足")).toBeTruthy();
    expect(screen.getByText("团队可能重派")).toBeTruthy();

    // 再点头部恢复展开。
    fireEvent.click(header);
    expect(screen.getByText(/course\.pptx 未生成/)).toBeTruthy();
  });

  it("badges known cutoff reason codes on gaps", () => {
    render(
      <DeliveryStatusCard
        status={{
          execution_id: "exec-4",
          state: "partial",
          summary: "已交付 1 个文件；1 项缺口",
          delivered_files: ["大纲.md"],
          gaps: [
            {
              role: "课件工程师",
              description: "队员因 token 预算触顶被迫收口，产出可能不完整",
              reason: "token_budget",
            },
          ],
          actions: [],
        }}
        conversationId="c1"
      />,
    );
    expect(screen.getAllByText("预算触顶").length).toBeGreaterThanOrEqual(1);
    // 描述仅在缺口明细行披露一次（摘要行已删除）。
    expect(screen.getAllByText(/token 预算触顶/).length).toBe(1);
  });

  it("bind_local_folder success auto-sends continue turn", async () => {
    const addMessage = vi.fn();
    getStateMock.mockReturnValue({ addMessage });
    pickAndBindLocalFolderMock.mockResolvedValue({
      ok: true,
      root: { id: "r1", name: "MyDocs" },
      binding: { rootId: "r1", mode: "local" },
    });

    render(<DeliveryStatusCard status={partial} conversationId="c1" />);
    fireEvent.click(screen.getByRole("button", { name: "绑定本地文件夹" }));

    await waitFor(() => {
      expect(pickAndBindLocalFolderMock).toHaveBeenCalledWith("c1");
      expect(addMessage).toHaveBeenCalled();
      expect(sendTurnMock).toHaveBeenCalledWith(
        expect.objectContaining({
          conversationId: "c1",
          content: expect.stringContaining("已绑定本地文件夹（MyDocs）"),
        }),
      );
    });
    expect(
      screen.getByText(/已绑定「MyDocs」为本机工作目录，正在让团队继续/),
    ).toBeTruthy();
  });

  it("renders website_verify action as a send button and posts the prompt", async () => {
    const addMessage = vi.fn();
    getStateMock.mockReturnValue({ addMessage });

    render(
      <DeliveryStatusCard
        status={{
          execution_id: "exec-5",
          state: "partial",
          summary: "已交付 3 个文件；1 项缺口",
          delivered_files: ["site/index.html"],
          gaps: [
            {
              role: "页面 QA",
              description: "整页验收波未跑（本回合预算用尽）",
              reason: "qa_deferred_budget",
            },
          ],
          actions: [
            {
              kind: "website_verify",
              description: "整页验收因预算推迟——点此续派页面 QA",
              prompt:
                '请对本站做第二段整页验收：delegate 时用 playbook=build_website_verify，playbook_args 填 site="GEO 官网"。',
            },
          ],
        }}
        conversationId="c1"
      />,
    );
    expect(screen.getByText("验收推迟")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "续派页面验收" }));
    await waitFor(() => {
      expect(addMessage).toHaveBeenCalled();
      expect(sendTurnMock).toHaveBeenCalledWith(
        expect.objectContaining({
          conversationId: "c1",
          content: expect.stringContaining("build_website_verify"),
        }),
      );
    });
  });

  it("renders continue_writing action as a send button and posts the prompt", async () => {
    const addMessage = vi.fn();
    getStateMock.mockReturnValue({ addMessage });

    render(
      <DeliveryStatusCard
        status={{
          execution_id: "exec-6",
          state: "partial",
          summary: "已交付 1 个文件；1 项缺口",
          delivered_files: ["报告.md"],
          gaps: [
            {
              role: "写作",
              description: "成篇未写完（章边界 / 预算）",
              reason: "token_budget",
            },
          ],
          actions: [
            {
              kind: "continue_writing",
              description:
                "成篇未写完——点此续写（从已完成章节继续；勿删稿重写整篇）",
              prompt:
                "请续写上一篇未完成的报告：先 file_read 已有草稿，从上一完整章之后用 file_append 按章续写；禁止 file_delete 后整篇重写。预算不够时仍停在章边界并诚实标 partial。",
            },
          ],
        }}
        conversationId="c1"
      />,
    );
    expect(screen.getByText("预算触顶")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "续写" }));
    await waitFor(() => {
      expect(addMessage).toHaveBeenCalled();
      expect(sendTurnMock).toHaveBeenCalledWith(
        expect.objectContaining({
          conversationId: "c1",
          content: expect.stringContaining("file_append"),
        }),
      );
    });
  });

  it("labels turn_token_budget and wires continue_skipped_runs", async () => {
    const addMessage = vi.fn();
    getStateMock.mockReturnValue({ addMessage });

    render(
      <DeliveryStatusCard
        status={{
          execution_id: "exec-7",
          state: "partial",
          summary: "已交付 1 个文件；1 项缺口",
          delivered_files: ["App.tsx"],
          gaps: [
            {
              role: "整合",
              description: "本回合累计 token 已触顶，未派发节点已跳过",
              reason: "turn_token_budget",
            },
          ],
          actions: [
            {
              kind: "continue_skipped_runs",
              description: "因额度未跑（整合）——点此下一回合续跑未执行节点",
              prompt:
                "请续跑上一回合因 token 额度跳过、从未开跑的节点：点名补跑 整合",
            },
          ],
        }}
        conversationId="c1"
      />,
    );
    expect(screen.getByText("回合额度触顶")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "续跑未执行节点" }));
    await waitFor(() => {
      expect(addMessage).toHaveBeenCalled();
      expect(sendTurnMock).toHaveBeenCalledWith(
        expect.objectContaining({
          conversationId: "c1",
          content: expect.stringContaining("整合"),
        }),
      );
    });
  });
});
