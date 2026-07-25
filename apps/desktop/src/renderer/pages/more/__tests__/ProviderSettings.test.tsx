// @vitest-environment jsdom
/**
 * Tests for 设置·服务商 (platform quota + BYOK providers).
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
vi.mock("@/services/llmProviders", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/services/llmProviders")>()),
  deleteLlmProvider: vi.fn(() => Promise.resolve({ status: "ok" })),
  testLlmProvider: vi.fn(() => Promise.resolve({})),
}));
vi.mock("@/components/llm/ModelKeyForm", async (importOriginal) => {
  const actual =
    await importOriginal<typeof import("@/components/llm/ModelKeyForm")>();
  return {
    ...actual,
    ModelKeyForm: () => <div data-testid="provider-form" />,
  };
});

import { useLlmProviders } from "@/hooks/useLlmProviders";
import { ApiError } from "@/services/api";
import type { LlmProvidersResponse } from "@/services/llmProviders";
import { deleteLlmProvider } from "@/services/llmProviders";
import { ProviderSettings } from "../ProviderSettings";

const useLlmProvidersMock = vi.mocked(useLlmProviders);

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
      },
      {
        id: "p2",
        label: "OpenAI",
        base_url: "https://api.openai.com/v1",
        default_model: "gpt-4o",
        status: "unchecked",
        masked_key: "••••wxyz",
      },
    ],
    default_model_profile_id: "sys-52",
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
      <ProviderSettings />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.mocked(deleteLlmProvider).mockClear();
});

afterEach(cleanup);

describe("ProviderSettings", () => {
  it("renders provider cards and the add affordance", () => {
    mockProviders(providersResponse());
    renderPage();
    expect(screen.getByText("DeepSeek")).toBeTruthy();
    expect(screen.getByText("OpenAI")).toBeTruthy();
    expect(screen.getByText(/••••abcd/)).toBeTruthy();
    expect(screen.getByText(/回落模型 deepseek-v4-pro/)).toBeTruthy();
    expect(screen.getByRole("button", { name: "添加服务商" })).toBeTruthy();
    expect(screen.queryByText("模型组合")).toBeNull();
  });

  it("shows a compact platform status line when the deployment offers platform models", () => {
    mockProviders(
      providersResponse({
        platform_available: true,
        platform_model: "deepseek-v4-flash",
      }),
    );
    renderPage();
    expect(screen.getByText("平台额度")).toBeTruthy();
    expect(screen.getByText(/平台模型 deepseek-v4-flash/)).toBeTruthy();
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
