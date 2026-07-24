// @vitest-environment jsdom
/**
 * Tests for 设置·模型配置 (multi-provider list page).
 *
 * Renders the platform-quota card + one card per BYOK provider (label, masked key, default
 * model, default badges), removes a provider through a confirm, and exposes the two
 * cross-provider account-default selectors grouped by provider.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/hooks/useLlmProviders", () => ({ useLlmProviders: vi.fn() }));
vi.mock("@/hooks/useModels", () => ({ useModels: vi.fn() }));
vi.mock("@/services/llmProviders", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/services/llmProviders")>()),
  deleteLlmProvider: vi.fn(() => Promise.resolve({ status: "ok" })),
  testLlmProvider: vi.fn(() => Promise.resolve({})),
  setLlmDefaults: vi.fn(),
}));
vi.mock("@/lib/capabilities", () => ({ hasLocalEngine: () => false }));
// The provider add/edit form pulls in write-side services; stub it to a marker.
vi.mock("@/components/llm/ModelKeyForm", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/components/llm/ModelKeyForm")>();
  return {
    ...actual,
    ModelKeyForm: () => <div data-testid="provider-form" />,
  };
});

import { useLlmProviders } from "@/hooks/useLlmProviders";
import { useModels } from "@/hooks/useModels";
import { ApiError } from "@/services/api";
import type { LlmProvidersResponse } from "@/services/llmProviders";
import { deleteLlmProvider } from "@/services/llmProviders";
import { ModelSettings } from "../ModelSettings";

const useLlmProvidersMock = vi.mocked(useLlmProviders);
const useModelsMock = vi.mocked(useModels);

function providersResponse(
  over: Partial<LlmProvidersResponse> = {},
): LlmProvidersResponse {
  return {
    providers: [
      {
        id: "p1",
        label: "DeepSeek",
        base_url: "https://api.deepseek.com/v1",
        default_model: "deepseek-v4-pro",
        status: "active",
        masked_key: "••••abcd",
        supports_tools: true,
        is_default_chat: true,
        is_default_background: false,
      },
      {
        id: "p2",
        label: "OpenAI",
        base_url: "https://api.openai.com/v1",
        default_model: "gpt-4o",
        status: "unchecked",
        masked_key: "••••wxyz",
        is_default_chat: false,
        is_default_background: false,
      },
    ],
    default_chat: { provider_id: "p1", model: "deepseek-v4-pro" },
    default_background: null,
    billing_mode: "byok",
    platform_available: false,
    platform_model: null,
    free_tier_active: false,
    ...over,
  };
}

function mockProviders(data: LlmProvidersResponse | undefined): void {
  useLlmProvidersMock.mockReturnValue({
    data,
    isLoading: false,
    isError: false,
  } as unknown as ReturnType<typeof useLlmProviders>);
}

function renderPage() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <ModelSettings />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
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
          provider_label: "DeepSeek",
          capabilities: [],
          available: true,
        },
        {
          id: "gpt-4o",
          origin: "byok",
          display_name: "GPT-4o",
          vendor: "OpenAI",
          provider_id: "p2",
          provider_label: "OpenAI",
          capabilities: [],
          available: true,
        },
      ],
    },
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useModels>);
  vi.mocked(deleteLlmProvider).mockClear();
});

afterEach(cleanup);

describe("ModelSettings (multi-provider)", () => {
  it("renders one card per provider with masked key, default model and default badge", () => {
    mockProviders(providersResponse());
    renderPage();
    expect(screen.getByText("DeepSeek")).toBeTruthy();
    expect(screen.getByText("OpenAI")).toBeTruthy();
    expect(screen.getByText("••••abcd")).toBeTruthy();
    expect(screen.getByText("默认模型 deepseek-v4-pro")).toBeTruthy();
    // The「聊天默认」badge (on the default provider's card) — the string also appears as
    // the chat-default selector label below, so assert at least one occurrence.
    expect(screen.getAllByText("聊天默认").length).toBeGreaterThan(0);
  });

  it("shows the read-only platform quota card when the deployment offers platform models", () => {
    mockProviders(
      providersResponse({
        platform_available: true,
        platform_model: "deepseek-v4-flash",
      }),
    );
    renderPage();
    expect(screen.getByText("平台额度")).toBeTruthy();
    expect(screen.getByText("默认平台模型 deepseek-v4-flash")).toBeTruthy();
  });

  it("confirms then deletes a provider", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    mockProviders(providersResponse());
    renderPage();
    fireEvent.click(screen.getAllByRole("button", { name: "删除" })[1]);
    expect(confirmSpy).toHaveBeenCalled();
    await waitFor(() =>
      expect(vi.mocked(deleteLlmProvider)).toHaveBeenCalledWith("p2"),
    );
    confirmSpy.mockRestore();
  });

  it("offers cross-provider default selectors grouped by provider", () => {
    mockProviders(providersResponse());
    const { container } = renderPage();
    expect(screen.getByText("账号默认模型")).toBeTruthy();
    const optgroups = container.querySelectorAll("optgroup");
    const labels = [...optgroups].map((g) => g.getAttribute("label"));
    expect(labels).toContain("DeepSeek");
    expect(labels).toContain("OpenAI");
  });

  it("renders the add-provider affordance", () => {
    mockProviders(providersResponse());
    renderPage();
    expect(screen.getByRole("button", { name: "添加服务商" })).toBeTruthy();
  });

  it("surfaces ADMIN_PRODUCT_FORBIDDEN instead of a generic load failure", () => {
    useLlmProvidersMock.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new ApiError(
        403,
        JSON.stringify({
          error: {
            code: "ADMIN_PRODUCT_FORBIDDEN",
            message: "管理员账号请使用管理后台登录",
          },
        }),
      ),
    } as unknown as ReturnType<typeof useLlmProviders>);
    renderPage();
    expect(
      screen.getByText("此账号为管理员账号，请使用管理后台登录"),
    ).toBeTruthy();
    expect(screen.queryByText("加载失败，请重试")).toBeNull();
  });

  it("maps 404 load failure to client version-mismatch copy", () => {
    useLlmProvidersMock.mockReturnValue({
      data: undefined,
      isLoading: false,
      isError: true,
      error: new ApiError(404, "{}"),
    } as unknown as ReturnType<typeof useLlmProviders>);
    renderPage();
    expect(
      screen.getByText("当前客户端版本过旧，请到设置 · 关于检查更新"),
    ).toBeTruthy();
    expect(screen.queryByText("加载失败，请重试")).toBeNull();
  });
});
