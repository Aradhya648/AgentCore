// @vitest-environment jsdom
/**
 * Render + interaction tests for the redesigned 设置·模型配置 provider list page.
 * Covers: provider cards from the list response, the platform-credit note, default-model
 * badges, and the account default selectors driving PUT /llm-providers/defaults. The REST
 * layer + ConfirmDialog (native <dialog>) are mocked so no real HTTP / showModal is needed.
 */
import type { LlmProvidersResponse } from "@/api/llmProviders";
import {
  deleteLlmProvider,
  listLlmProviders,
  setLlmDefaults,
  testLlmProvider,
} from "@/api/llmProviders";
import type { ModelCatalog } from "@/api/models";
import { ModelSettings } from "@/pages/more/ModelSettings";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/api/llmProviders", () => ({
  listLlmProviders: vi.fn(),
  setLlmDefaults: vi.fn(),
  testLlmProvider: vi.fn(),
  deleteLlmProvider: vi.fn(),
  createLlmProvider: vi.fn(),
  updateLlmProvider: vi.fn(),
}));

vi.mock("@/components/conversations", () => ({ ConfirmDialog: () => null }));

vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>(
      "react-router-dom",
    );
  return { ...actual, useNavigate: () => vi.fn() };
});

const CATALOG: ModelCatalog = {
  byok_configured: true,
  current: {
    id: "deepseek-v4-pro",
    origin: "byok",
    provider_id: "prov-deepseek",
  },
  models: [
    {
      id: "deepseek-v4-pro",
      origin: "byok",
      provider_id: "prov-deepseek",
      provider_label: "DeepSeek",
      display_name: "DeepSeek V4 Pro",
      vendor: "DeepSeek",
      capabilities: [],
      context_length: null,
      price: null,
      available: true,
    },
    {
      id: "gpt-4o",
      origin: "byok",
      provider_id: "prov-openai",
      provider_label: "OpenAI",
      display_name: "GPT-4o",
      vendor: "OpenAI",
      capabilities: [],
      context_length: null,
      price: null,
      available: true,
    },
  ],
};

vi.mock("@/api/models", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/models")>();
  return {
    ...actual,
    useModels: () => ({
      data: CATALOG,
      loading: false,
      error: null,
      refetch: vi.fn(),
    }),
  };
});

const mockList = vi.mocked(listLlmProviders);
const mockSetDefaults = vi.mocked(setLlmDefaults);
vi.mocked(testLlmProvider);
vi.mocked(deleteLlmProvider);

function makeResponse(
  overrides: Partial<LlmProvidersResponse> = {},
): LlmProvidersResponse {
  return {
    providers: [
      {
        id: "prov-deepseek",
        label: "DeepSeek",
        base_url: "https://api.deepseek.com",
        default_model: "deepseek-v4-pro",
        status: "active",
        is_default_chat: true,
        is_default_background: false,
        masked_key: "sk-…abcd",
        supports_tools: true,
      },
      {
        id: "prov-openai",
        label: "OpenAI",
        base_url: "https://api.openai.com/v1",
        default_model: "gpt-4o",
        status: "unchecked",
        is_default_chat: false,
        is_default_background: false,
        masked_key: "sk-…wxyz",
      },
    ],
    billing_mode: "platform",
    platform_available: true,
    platform_model: "deepseek-v4-pro",
    free_tier_active: false,
    default_chat: { provider_id: "prov-deepseek", model: "deepseek-v4-pro" },
    default_background: null,
    ...overrides,
  };
}

afterEach(cleanup);
beforeEach(() => {
  mockList.mockReset();
  mockSetDefaults.mockReset();
});

describe("ModelSettings (provider list)", () => {
  it("renders configured provider cards with host, model and the default badge", async () => {
    mockList.mockResolvedValue(makeResponse());
    render(<ModelSettings />);

    await waitFor(() => expect(screen.getByText("DeepSeek")).toBeTruthy());
    expect(screen.getByText("OpenAI")).toBeTruthy();
    expect(screen.getByText("api.deepseek.com")).toBeTruthy();
    expect(screen.getByText("模型 deepseek-v4-pro")).toBeTruthy();
    expect(screen.getByText("对话默认")).toBeTruthy();
    expect(screen.getAllByTestId("provider-card")).toHaveLength(2);
  });

  it("shows the platform-credit note when the deployment offers platform models", async () => {
    mockList.mockResolvedValue(makeResponse());
    render(<ModelSettings />);
    await waitFor(() =>
      expect(screen.getByText(/不接入也可用平台额度直接对话/)).toBeTruthy(),
    );
  });

  it("sets the account chat default via the cross-provider selector", async () => {
    mockList.mockResolvedValue(makeResponse());
    mockSetDefaults.mockResolvedValue(
      makeResponse({
        default_chat: { provider_id: "prov-openai", model: "gpt-4o" },
      }),
    );
    render(<ModelSettings />);

    const chat = (await screen.findByLabelText(
      "对话默认模型",
    )) as HTMLSelectElement;
    expect(chat.value).toBe("prov-deepseek::deepseek-v4-pro");

    fireEvent.change(chat, { target: { value: "prov-openai::gpt-4o" } });
    await waitFor(() =>
      expect(mockSetDefaults).toHaveBeenCalledWith({
        chat: { provider_id: "prov-openai", model: "gpt-4o" },
      }),
    );
  });

  it("clears the background default to follow chat", async () => {
    mockList.mockResolvedValue(
      makeResponse({
        default_background: { provider_id: "prov-openai", model: "gpt-4o" },
      }),
    );
    mockSetDefaults.mockResolvedValue(makeResponse());
    render(<ModelSettings />);

    const bg = (await screen.findByLabelText(
      "后台默认模型",
    )) as HTMLSelectElement;
    expect(bg.value).toBe("prov-openai::gpt-4o");

    fireEvent.change(bg, { target: { value: "" } });
    await waitFor(() =>
      expect(mockSetDefaults).toHaveBeenCalledWith({ background: null }),
    );
  });

  it("surfaces ADMIN_PRODUCT_FORBIDDEN instead of a generic load failure", async () => {
    mockList.mockRejectedValue(
      new Error("此账号为管理员账号，请使用管理后台登录"),
    );
    render(<ModelSettings />);
    await waitFor(() =>
      expect(
        screen.getByText("此账号为管理员账号，请使用管理后台登录"),
      ).toBeTruthy(),
    );
    expect(screen.queryByText("加载失败，请重试")).toBeNull();
  });
});
