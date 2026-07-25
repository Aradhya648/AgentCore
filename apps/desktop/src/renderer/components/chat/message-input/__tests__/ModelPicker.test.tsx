// @vitest-environment jsdom
/**
 * Tests for the input-box model profile picker (模型组合).
 *
 * Lists system + user combinations, follows account default, PATCHes
 * `model_profile_id`, inherits last-used profile on a fresh chat, and links to
 * settings for management.
 */

import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/hooks/useLlmModelProfiles", () => ({
  useLlmModelProfiles: vi.fn(),
}));
vi.mock("@/hooks/useModels", () => ({ useModels: vi.fn() }));
vi.mock("@/hooks/useConversations", () => ({
  useConversations: vi.fn(() => []),
  patchConversationCache: vi.fn(),
}));
vi.mock("@/services/conversations", () => ({
  setConversationModelProfile: vi.fn(),
}));
vi.mock("@/lib/toast", () => ({
  notifySuccess: vi.fn(),
  notifyError: vi.fn(),
}));

import { TooltipProvider } from "@/components/ui/tooltip";
import {
  patchConversationCache,
  useConversations,
} from "@/hooks/useConversations";
import { useLlmModelProfiles } from "@/hooks/useLlmModelProfiles";
import { useModels } from "@/hooks/useModels";
import { __setUiStorageBackendForTests } from "@/lib/uiStorage";
import { setConversationModelProfile } from "@/services/conversations";
import type { LlmModelProfileListResponse } from "@/services/llmModelProfiles";
import { setLastUsedProfileId } from "@/services/models";
import { useConversationStore } from "@/stores/conversation";
import type { Conversation } from "@/stores/conversation";
import { ModelPicker } from "../ModelPicker";

const useProfilesMock = vi.mocked(useLlmModelProfiles);
const useModelsMock = vi.mocked(useModels);
const useConversationsMock = vi.mocked(useConversations);
const setProfileMock = vi.mocked(setConversationModelProfile);

function profiles(
  over: Partial<LlmModelProfileListResponse> = {},
): LlmModelProfileListResponse {
  return {
    default_model_profile_id: "sys-52",
    data: [
      {
        id: "sys-52",
        name: "5.2",
        kind: "system",
        is_default: true,
        main: { origin: "byok", provider_id: "p1", model: "deepseek-v4-pro" },
        worker: null,
        background: null,
      },
      {
        id: "sys-grok",
        name: "Grok 4.5",
        kind: "system",
        is_default: false,
        main: { origin: "byok", provider_id: "p2", model: "gpt-4o" },
        worker: { origin: "byok", provider_id: "p1", model: "deepseek-v4-pro" },
        background: null,
      },
      {
        id: "user-mine",
        name: "办公",
        kind: "user",
        is_default: false,
        main: { origin: "platform", provider_id: null, model: "flash" },
        worker: null,
        background: null,
      },
    ],
    ...over,
  };
}

function mockProfiles(data: LlmModelProfileListResponse | undefined): void {
  useProfilesMock.mockReturnValue({
    data,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useLlmModelProfiles>);
}

function conv(partial: Partial<Conversation> & { id: string }): Conversation {
  return {
    title: "T",
    updatedAt: "",
    messageCount: 0,
    lastMessagePreview: null,
    ...partial,
  } as Conversation;
}

function renderPicker() {
  return render(
    <MemoryRouter>
      <TooltipProvider>
        <ModelPicker />
      </TooltipProvider>
    </MemoryRouter>,
  );
}

beforeEach(() => {
  const store = new Map<string, string>();
  __setUiStorageBackendForTests({
    getItem: (k) => store.get(k) ?? null,
    setItem: (k, v) => {
      store.set(k, v);
    },
    removeItem: (k) => {
      store.delete(k);
    },
    keys: () => [...store.keys()],
  });
  useConversationStore.setState({ currentConversationId: null, byId: {} });
  useConversationsMock.mockReturnValue([]);
  useModelsMock.mockReturnValue({
    data: {
      byok_configured: true,
      current: { id: "deepseek-v4-pro", origin: "byok", provider_id: "p1" },
      models: [
        {
          id: "deepseek-v4-pro",
          origin: "byok",
          display_name: "DeepSeek V4 Pro",
          vendor: "DeepSeek",
          provider_id: "p1",
          capabilities: [],
          available: true,
        },
        {
          id: "gpt-4o",
          origin: "byok",
          display_name: "GPT-4o",
          vendor: "OpenAI",
          provider_id: "p2",
          capabilities: [],
          available: true,
        },
        {
          id: "flash",
          origin: "platform",
          display_name: "Flash",
          vendor: "Platform",
          capabilities: [],
          available: true,
        },
      ],
    },
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useModels>);
  setProfileMock.mockReset();
  vi.mocked(patchConversationCache).mockReset();
});

afterEach(() => {
  __setUiStorageBackendForTests(null);
  cleanup();
});

describe("ModelPicker", () => {
  it("shows the account default profile on a fresh conversation", () => {
    mockProfiles(profiles());
    renderPicker();
    expect(screen.getByText("5.2")).toBeTruthy();
    expect(screen.getByText(/DeepSeek V4 Pro · 跟随主模型/)).toBeTruthy();
  });

  it("shows the conversation's profile override over the account default", () => {
    useConversationStore.setState({ currentConversationId: "c1", byId: {} });
    useConversationsMock.mockReturnValue([
      conv({ id: "c1", modelProfileId: "sys-grok" }),
    ]);
    mockProfiles(profiles());
    renderPicker();
    expect(screen.getByText("Grok 4.5")).toBeTruthy();
  });

  it("lists system + user profiles and a manage link", () => {
    mockProfiles(profiles());
    renderPicker();
    fireEvent.click(screen.getByRole("button", { name: /模型组合：/ }));
    expect(screen.getByText("跟随账号默认")).toBeTruthy();
    expect(screen.getByText("系统预置")).toBeTruthy();
    expect(screen.getByText("我的组合")).toBeTruthy();
    expect(screen.getByText("管理组合…")).toBeTruthy();
    // No bare model catalog rows.
    expect(screen.queryByText("自带 Key")).toBeNull();
  });

  it("persists the pick via PATCH model_profile_id", async () => {
    useConversationStore.setState({ currentConversationId: "c1", byId: {} });
    useConversationsMock.mockReturnValue([
      conv({ id: "c1", modelProfileId: null }),
    ]);
    mockProfiles(profiles());
    setProfileMock.mockResolvedValue(
      conv({ id: "c1", modelProfileId: "user-mine" }),
    );

    renderPicker();
    fireEvent.click(screen.getByRole("button", { name: /模型组合：/ }));
    fireEvent.click(screen.getByText("办公"));

    await waitFor(() =>
      expect(setProfileMock).toHaveBeenCalledWith("c1", "user-mine"),
    );
    expect(patchConversationCache).toHaveBeenCalledWith("c1", {
      modelProfileId: "user-mine",
    });
  });

  it("clears the override when following account default", async () => {
    useConversationStore.setState({ currentConversationId: "c1", byId: {} });
    useConversationsMock.mockReturnValue([
      conv({ id: "c1", modelProfileId: "user-mine" }),
    ]);
    mockProfiles(profiles());
    setProfileMock.mockResolvedValue(conv({ id: "c1", modelProfileId: null }));

    renderPicker();
    fireEvent.click(screen.getByRole("button", { name: /模型组合：/ }));
    fireEvent.click(screen.getByText("跟随账号默认"));

    await waitFor(() =>
      expect(setProfileMock).toHaveBeenCalledWith("c1", null),
    );
  });

  it("inherits the last-used profile id as the suggestion on a new chat", () => {
    setLastUsedProfileId("sys-grok");
    mockProfiles(profiles());
    renderPicker();
    expect(screen.getByText("Grok 4.5")).toBeTruthy();
  });
});
