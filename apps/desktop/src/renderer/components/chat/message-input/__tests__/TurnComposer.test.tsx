// @vitest-environment jsdom
/**
 * TurnComposer variant smoke: `card` keeps the full toolbar; `bar` collapses
 * extras behind the「更多」entry and exposes `data-composer-variant`.
 */

import { TooltipProvider } from "@/components/ui/tooltip";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/hooks/useLlmProviders", () => ({
  useLlmProviders: () => ({
    data: {
      providers: [
        {
          id: "p1",
          label: "DeepSeek",
          base_url: "https://api.deepseek.com/v1",
          default_model: "deepseek-test",
          status: "active",
          supports_tools: true,
        },
      ],
      default_model_profile_id: "sys-52",
      billing_mode: "byok",
      platform_available: false,
      platform_model: null,
    },
    isLoading: false,
  }),
}));
vi.mock("@/hooks/useLlmModelProfiles", () => ({
  useLlmModelProfiles: () => ({
    data: {
      default_model_profile_id: "sys-52",
      data: [
        {
          id: "sys-52",
          name: "GLM-5.2",
          kind: "system",
          is_default: true,
          main: {
            origin: "byok",
            provider_id: "p1",
            model: "deepseek-test",
          },
          worker: null,
          background: null,
        },
      ],
    },
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
}));
vi.mock("@/hooks/useFolders", () => ({
  useFolders: () => [],
  useCreateFolder: () => ({ mutateAsync: vi.fn() }),
}));
vi.mock("@/hooks/useConversations", () => ({
  useConversations: () => [],
  useGroupedConversations: () => ({ data: { folders: [] } }),
  patchConversationCache: vi.fn(),
}));
vi.mock("@/hooks/useModels", () => ({
  useModels: () => ({
    data: {
      byok_configured: true,
      current: { id: "deepseek-test", origin: "byok" },
      models: [
        {
          id: "deepseek-test",
          origin: "byok",
          display_name: "DeepSeek Test",
          vendor: "DeepSeek",
          capabilities: [],
          context_length: null,
          price: null,
          available: true,
        },
      ],
    },
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  }),
}));
vi.mock("@/lib/capabilities", () => ({
  hasLocalFiles: () => false,
}));
vi.mock("@/services/permissionAxes", () => ({
  RECIPE_LABELS: {
    cautious: { short: "谨慎", description: "问" },
    less_interrupt: { short: "少打断", description: "少" },
    managed: { short: "托管", description: "同权" },
  },
  RECIPE_ORDER: ["cautious", "less_interrupt", "managed"],
  RECIPE_AXES: {
    less_interrupt: {
      file_write: "session",
      command: "auto",
      team_kickoff: "rules",
      host: "ask",
    },
  },
  DEFAULT_PERMISSION_AXES: {
    file_write: "session",
    command: "auto",
    team_kickoff: "rules",
    host: "ask",
  },
  FILE_WRITE_OPTIONS: [],
  COMMAND_OPTIONS: [],
  TEAM_KICKOFF_OPTIONS: [],
  matchRecipe: () => "less_interrupt",
  axesShortLabel: () => "少打断",
  recipeToAxes: () => ({
    file_write: "session",
    command: "auto",
    team_kickoff: "rules",
    host: "ask",
  }),
  resolveDefaultPermissionAxes: () =>
    Promise.resolve({
      file_write: "session",
      command: "auto",
      team_kickoff: "rules",
      host: "ask",
    }),
  setConversationPermissionAxes: vi.fn(),
  setComposerDraftAxes: vi.fn(),
  confirmAutoCommandIfNeeded: () => true,
  isIllegalAxes: () => false,
}));
vi.mock("@/components/chat/message-input/useVoiceInput", () => ({
  useVoiceInput: () => ({
    isSupported: false,
    isRecording: false,
    interimText: "",
    duration: 0,
    state: "idle",
    toggle: vi.fn(),
    cancel: vi.fn(),
    stop: vi.fn(),
  }),
}));
vi.mock("@/components/chat/message-input/useComposerDrop", () => ({
  useComposerDrop: () => ({
    dragOver: false,
    dropError: null,
    clearDropError: vi.fn(),
    handleDragOver: vi.fn(),
    handleDragLeave: vi.fn(),
    handleDrop: vi.fn(),
    handlePaste: vi.fn(),
  }),
}));
vi.mock("@/components/chat/message-input/useComposerSend", () => ({
  useComposerSend: () => ({ handleSend: vi.fn() }),
}));
vi.mock("@/components/chat/message-input/useMentionMenu", () => ({
  useMentionMenu: () => ({
    menuMode: null,
    items: [],
    activeIndex: 0,
    indexLoading: false,
    menuError: null,
    query: "",
    sourceCount: 0,
    indexLoadedRef: { current: true },
    searchInputRef: { current: null },
    closeMenu: vi.fn(),
    syncMention: vi.fn(),
    handleMenuNavKey: () => false,
    attachEntry: vi.fn(),
    setActiveIndex: vi.fn(),
    setQuery: vi.fn(),
    handleAddRoot: vi.fn(),
    pickLocalFile: vi.fn(),
  }),
}));

// isGenerating 来自 activeRuntime().isGenerating（非顶层字段），构造完整 runtime 太脆，
// 直接 mock 这个 hook；其余 store 行为（setState / getState）保留真实实现。
const genMock = vi.hoisted(() => ({ value: false }));
vi.mock("@/stores/conversation", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/stores/conversation")>();
  return { ...actual, useActiveGenerating: () => genMock.value };
});

import { useConversationStore } from "@/stores/conversation";
import { useServerHealthStore } from "@/stores/serverHealth";
import { TurnComposer } from "../TurnComposer";

function renderComposer(variant?: "card" | "bar") {
  return render(
    <MemoryRouter>
      <TooltipProvider>
        <TurnComposer variant={variant} />
      </TooltipProvider>
    </MemoryRouter>,
  );
}

beforeEach(async () => {
  genMock.value = false;
  useConversationStore.setState({
    currentConversationId: null,
    byId: {},
  } as never);
  useServerHealthStore.setState({
    status: "online",
    reason: null,
    justRecovered: false,
  });
  const { useComposerDraftStore } = await import("@/stores/composer");
  useComposerDraftStore.getState().setValue("__draft__", "");
});

afterEach(cleanup);

describe("TurnComposer variants", () => {
  it("defaults to card: toolbar badges visible, no「更多」entry", () => {
    const { container } = renderComposer();
    expect(
      container.querySelector('[data-composer-variant="card"]'),
    ).toBeTruthy();
    expect(screen.queryByRole("button", { name: "更多选项" })).toBeNull();
    expect(screen.getByLabelText(/模型组合：/)).toBeTruthy();
    expect(screen.getByLabelText("附加本机文件")).toBeTruthy();
  });

  it("bar: single-row chrome with「更多」popover hosting the four extras", async () => {
    const { container } = renderComposer("bar");
    expect(
      container.querySelector('[data-composer-variant="bar"]'),
    ).toBeTruthy();
    expect(screen.getByRole("button", { name: "更多选项" })).toBeTruthy();
    expect(screen.getByLabelText("附加本机文件")).toBeTruthy();
    // Badges live inside the popover — not in the bar until opened.
    expect(screen.queryByLabelText(/模型组合：/)).toBeNull();

    fireEvent.click(screen.getByRole("button", { name: "更多选项" }));
    expect(await screen.findByLabelText(/模型组合：/)).toBeTruthy();
    expect(screen.getByLabelText(/权限：/)).toBeTruthy();
    expect(screen.getByLabelText("在哪工作")).toBeTruthy();
  });

  it("bar: healthy server shows no status red-dot on「更多」", () => {
    renderComposer("bar");
    const more = screen.getByRole("button", { name: "更多选项" });
    expect(more.querySelector(".bg-destructive")).toBeNull();
  });

  it("bar: offline server hangs a destructive red-dot on「更多」", () => {
    useServerHealthStore.setState({
      status: "offline",
      reason: "unreachable",
      justRecovered: false,
    });
    renderComposer("bar");
    const more = screen.getByRole("button", { name: "更多选项" });
    expect(more.querySelector(".bg-destructive")).toBeTruthy();
  });

  it("N4-A: offline hard-disables 发送 even with draft text", async () => {
    useServerHealthStore.setState({
      status: "offline",
      reason: "unreachable",
      justRecovered: false,
    });
    const { useComposerDraftStore } = await import("@/stores/composer");
    useComposerDraftStore.getState().setValue("__draft__", "hello offline");
    renderComposer("bar");
    const send = screen.getByRole("button", { name: "发送" });
    expect((send as HTMLButtonElement).disabled).toBe(true);
    expect(
      screen.getByText(/可浏览已缓存的对话与本机文件（只读）/),
    ).toBeTruthy();
  });

  it("generating + empty: bar shows only 停止生成 (no 插话)", () => {
    genMock.value = true;
    renderComposer("bar");
    expect(screen.queryByRole("button", { name: "发送插话" })).toBeNull();
    expect(screen.getByRole("button", { name: "停止生成" })).toBeTruthy();
  });

  it("generating + draft: muted 发送插话 + solid 停止生成", async () => {
    genMock.value = true;
    const { useComposerDraftStore } = await import("@/stores/composer");
    useComposerDraftStore.getState().setValue("__draft__", "插一句");
    renderComposer("bar");
    expect(screen.getByRole("button", { name: "发送插话" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "停止生成" })).toBeTruthy();
    expect(screen.getByText(/Enter 或点发送将作为插话交给团队/)).toBeTruthy();
  });

  it("generating + draft: canvas card also exposes muted 插话 + 停止", async () => {
    genMock.value = true;
    const { useComposerDraftStore } = await import("@/stores/composer");
    useComposerDraftStore.getState().setValue("__draft__", "插一句");
    renderComposer();
    expect(screen.getByRole("button", { name: "发送插话" })).toBeTruthy();
    expect(screen.getByRole("button", { name: "停止生成" })).toBeTruthy();
  });

  it("idle: single 发送, no 插话 / 停止", () => {
    renderComposer("bar");
    expect(screen.queryByRole("button", { name: "发送插话" })).toBeNull();
    expect(screen.queryByRole("button", { name: "停止生成" })).toBeNull();
    expect(screen.getByRole("button", { name: "发送" })).toBeTruthy();
  });
});
