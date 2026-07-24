// @vitest-environment jsdom
/**
 * Tests for the input-box model picker (会话级模型切换).
 *
 * The picker's data source is the model catalog (`GET /v1/users/me/models`) — it lists
 * catalog models with the platform group flat (no per-vendor sub-headers) and the BYOK
 * group by 服务商 (provider_label), greys out unavailable ones with an unlock guide,
 * switches the active
 * conversation via PATCH with (id, origin, provider_id), inherits the last-used pick on a
 * fresh chat, and still truthfully echoes the last-actually-ran model.
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

vi.mock("@/hooks/useModels", () => ({ useModels: vi.fn() }));
vi.mock("@/hooks/useConversations", () => ({
  useConversations: vi.fn(() => []),
  patchConversationCache: vi.fn(),
}));
vi.mock("@/services/conversations", () => ({
  setConversationModel: vi.fn(),
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
import { useModels } from "@/hooks/useModels";
import { __setUiStorageBackendForTests } from "@/lib/uiStorage";
import { setConversationModel } from "@/services/conversations";
import { type ModelCatalog, setLastUsedModel } from "@/services/models";
import { useConversationStore } from "@/stores/conversation";
import type { Conversation } from "@/stores/conversation";
import { useTurnModelStore } from "@/stores/turnModel";
import { ModelPicker } from "../ModelPicker";

const useModelsMock = vi.mocked(useModels);
const useConversationsMock = vi.mocked(useConversations);
const setConversationModelMock = vi.mocked(setConversationModel);

function catalog(over: Partial<ModelCatalog> = {}): ModelCatalog {
  return {
    byok_configured: true,
    current: {
      id: "deepseek-v4-pro",
      origin: "byok",
      provider_id: "p-deepseek",
    },
    models: [
      {
        id: "deepseek-v4-pro",
        origin: "byok",
        display_name: "DeepSeek V4 Pro",
        vendor: "DeepSeek",
        provider_id: "p-deepseek",
        provider_label: "DeepSeek",
        capabilities: ["tools", "reasoning"],
        context_length: 128000,
        price: { cache_miss: "0.14", output: "0.28", cache_hit: null },
        available: true,
      },
      {
        id: "gpt-4o",
        origin: "byok",
        display_name: "GPT-4o",
        vendor: "OpenAI",
        provider_id: "p-openai",
        provider_label: "OpenAI",
        capabilities: ["vision", "tools"],
        context_length: 128000,
        price: null,
        available: true,
      },
      {
        id: "o3",
        origin: "byok",
        display_name: "o3",
        vendor: "OpenAI",
        provider_id: "p-openai",
        provider_label: "OpenAI",
        capabilities: ["reasoning"],
        context_length: 200000,
        price: null,
        available: false,
      },
    ],
    ...over,
  };
}

function mockModels(data: ModelCatalog | undefined, opts = {}): void {
  useModelsMock.mockReturnValue({
    data,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
    ...opts,
  } as unknown as ReturnType<typeof useModels>);
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
  useTurnModelStore.setState({ byConversation: {} });
  useConversationsMock.mockReturnValue([]);
  setConversationModelMock.mockReset();
  vi.mocked(patchConversationCache).mockReset();
});

afterEach(() => {
  __setUiStorageBackendForTests(null);
  cleanup();
});

describe("ModelPicker", () => {
  it("shows the account's current model on a fresh conversation", () => {
    mockModels(catalog());
    renderPicker();
    expect(screen.getByText("DeepSeek V4 Pro")).toBeTruthy();
  });

  it("shows the conversation's model override over the account default", () => {
    useConversationStore.setState({ currentConversationId: "c1", byId: {} });
    useConversationsMock.mockReturnValue([
      conv({
        id: "c1",
        model: "gpt-4o",
        modelOrigin: "byok",
        modelProviderId: "p-openai",
      }),
    ]);
    mockModels(catalog());
    renderPicker();
    expect(screen.getByText("GPT-4o")).toBeTruthy();
  });

  it("truthfully echoes the last actually-ran model when there is no override", () => {
    useConversationStore.setState({ currentConversationId: "c1", byId: {} });
    useConversationsMock.mockReturnValue([conv({ id: "c1", model: null })]);
    useTurnModelStore.setState({ byConversation: { c1: "gpt-4o" } });
    mockModels(catalog());
    renderPicker();
    expect(screen.getByText("GPT-4o")).toBeTruthy();
    expect(screen.queryByText("DeepSeek V4 Pro")).toBeNull();
  });

  it("lists catalog models grouped by origin then 服务商 and greys unavailable ones", () => {
    mockModels(catalog());
    renderPicker();
    fireEvent.click(screen.getByRole("button", { name: /模型：/ }));
    expect(screen.getByText("自带 Key")).toBeTruthy();
    // BYOK group headers are the provider labels (not vendor guesses).
    expect(screen.getByText("OpenAI")).toBeTruthy();
    expect(screen.getByText("DeepSeek")).toBeTruthy();
    expect(screen.getByText("接入自己的 Key 解锁")).toBeTruthy();
  });

  it("persists the pick to the active conversation via PATCH with (origin, provider_id)", async () => {
    useConversationStore.setState({ currentConversationId: "c1", byId: {} });
    useConversationsMock.mockReturnValue([conv({ id: "c1", model: null })]);
    mockModels(catalog());
    setConversationModelMock.mockResolvedValue(
      conv({
        id: "c1",
        model: "gpt-4o",
        modelOrigin: "byok",
        modelProviderId: "p-openai",
      }),
    );

    renderPicker();
    fireEvent.click(screen.getByRole("button", { name: /模型：/ }));
    fireEvent.click(screen.getByText("GPT-4o"));

    await waitFor(() =>
      expect(setConversationModelMock).toHaveBeenCalledWith("c1", {
        id: "gpt-4o",
        origin: "byok",
        providerId: "p-openai",
      }),
    );
    expect(patchConversationCache).toHaveBeenCalledWith("c1", {
      model: "gpt-4o",
      modelOrigin: "byok",
      modelProviderId: "p-openai",
    });
  });

  it("does not PATCH an unavailable model (guides to key setup instead)", () => {
    useConversationStore.setState({ currentConversationId: "c1", byId: {} });
    useConversationsMock.mockReturnValue([conv({ id: "c1", model: null })]);
    mockModels(catalog());

    renderPicker();
    fireEvent.click(screen.getByRole("button", { name: /模型：/ }));
    fireEvent.click(screen.getByText("o3"));

    expect(setConversationModelMock).not.toHaveBeenCalled();
  });

  it("inherits the last-used (id, origin, provider_id) as the suggestion on a new chat", () => {
    setLastUsedModel({ id: "gpt-4o", origin: "byok", providerId: "p-openai" });
    mockModels(catalog());
    renderPicker();
    expect(screen.getByText("GPT-4o")).toBeTruthy();
  });

  it("shows a 平台额度 badge on platform rows when the same id exists under BYOK", () => {
    mockModels(
      catalog({
        byok_configured: false,
        current: { id: "deepseek-v4-pro", origin: "platform" },
        models: [
          {
            id: "deepseek-v4-pro",
            origin: "platform",
            display_name: "DeepSeek V4 Pro",
            vendor: "DeepSeek",
            capabilities: [],
            context_length: 128000,
            price: null,
            available: true,
          },
          {
            id: "deepseek-v4-pro",
            origin: "byok",
            display_name: "DeepSeek V4 Pro",
            vendor: "DeepSeek",
            provider_id: "p-deepseek",
            provider_label: "DeepSeek",
            capabilities: [],
            context_length: 128000,
            price: null,
            available: false,
          },
        ],
      }),
    );
    renderPicker();
    fireEvent.click(screen.getByRole("button", { name: /模型：/ }));
    expect(screen.getByText("平台额度")).toBeTruthy();
    expect(screen.getByText("平台模型")).toBeTruthy();
  });

  it("renders the platform group flat — no per-vendor sub-headers", () => {
    mockModels(
      catalog({
        byok_configured: false,
        current: { id: "5.2", origin: "platform" },
        models: [
          {
            id: "5.2",
            origin: "platform",
            display_name: "5.2",
            vendor: "平台中转",
            capabilities: ["tools", "reasoning"],
            context_length: 128000,
            price: { cache_miss: "2.50", output: "10.00", cache_hit: null },
            available: true,
          },
          {
            id: "grok-4.5",
            origin: "platform",
            display_name: "Grok 4.5",
            vendor: "xAI",
            capabilities: ["tools", "reasoning"],
            context_length: 256000,
            price: { cache_miss: "3.00", output: "15.00", cache_hit: null },
            available: true,
          },
        ],
      }),
    );
    renderPicker();
    fireEvent.click(screen.getByRole("button", { name: /模型：/ }));
    // One「平台模型」origin header, models listed flat underneath.
    expect(screen.getByText("平台模型")).toBeTruthy();
    expect(screen.getAllByText("5.2").length).toBeGreaterThan(0);
    expect(screen.getAllByText("Grok 4.5").length).toBeGreaterThan(0);
    // No vendor sub-headers (the whole point of flattening the platform group).
    expect(screen.queryByText("平台中转")).toBeNull();
    expect(screen.queryByText("xAI")).toBeNull();
  });
});
