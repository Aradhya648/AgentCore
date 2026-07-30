// @vitest-environment jsdom
/**
 * Tests for 设置·模型 (model combinations / account default profile).
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { MemoryRouter } from "react-router-dom";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

vi.mock("@/hooks/useLlmProviders", () => ({ useLlmProviders: vi.fn() }));
vi.mock("@/hooks/useLlmModelProfiles", () => ({
  useLlmModelProfiles: vi.fn(),
}));
vi.mock("@/hooks/useModels", () => ({ useModels: vi.fn() }));
vi.mock("@/lib/toast", () => ({
  notifySuccess: vi.fn(),
}));
vi.mock("@/services/llmModelProfiles", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/services/llmModelProfiles")>()),
  createLlmModelProfile: vi.fn(),
  updateLlmModelProfile: vi.fn(),
  deleteLlmModelProfile: vi.fn(() => Promise.resolve({ status: "ok" })),
  setDefaultLlmModelProfile: vi.fn(),
}));

import { TooltipProvider } from "@/components/ui/tooltip";
import { useLlmModelProfiles } from "@/hooks/useLlmModelProfiles";
import { useLlmProviders } from "@/hooks/useLlmProviders";
import { useModels } from "@/hooks/useModels";
import { notifySuccess } from "@/lib/toast";
import { ApiError } from "@/services/api";
import type { LlmModelProfileListResponse } from "@/services/llmModelProfiles";
import {
  createLlmModelProfile,
  deleteLlmModelProfile,
  setDefaultLlmModelProfile,
  updateLlmModelProfile,
} from "@/services/llmModelProfiles";
import type { LlmProvidersResponse } from "@/services/llmProviders";
import { ModelSettings } from "../ModelSettings";

const useLlmProvidersMock = vi.mocked(useLlmProviders);
const useProfilesMock = vi.mocked(useLlmModelProfiles);
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

function profilesResponse(
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
        id: "user-mine",
        name: "办公",
        kind: "user",
        is_default: false,
        main: { origin: "byok", provider_id: "p2", model: "gpt-4o" },
        worker: null,
        background: null,
      },
    ],
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

function mockProfiles(data: LlmModelProfileListResponse | undefined): void {
  useProfilesMock.mockReturnValue({
    data,
    isLoading: false,
    isError: false,
    refetch: vi.fn(),
  } as unknown as ReturnType<typeof useLlmModelProfiles>);
}

function renderPage() {
  return render(
    <MemoryRouter>
      <QueryClientProvider client={new QueryClient()}>
        <TooltipProvider>
          <ModelSettings />
        </TooltipProvider>
      </QueryClientProvider>
    </MemoryRouter>,
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
  mockProfiles(profilesResponse());
  vi.mocked(deleteLlmModelProfile).mockClear();
  vi.mocked(setDefaultLlmModelProfile).mockClear();
  vi.mocked(createLlmModelProfile).mockClear();
  vi.mocked(updateLlmModelProfile).mockClear();
  vi.mocked(notifySuccess).mockClear();
});

afterEach(cleanup);

describe("ModelSettings (profiles)", () => {
  it("renders model combinations without provider key cards", () => {
    mockProviders(providersResponse());
    renderPage();
    expect(screen.getByText("模型组合")).toBeTruthy();
    expect(screen.getByText("5.2")).toBeTruthy();
    expect(screen.getByText("办公")).toBeTruthy();
    expect(screen.getByText("默认组合")).toBeTruthy();
    expect(screen.queryByText("••••abcd")).toBeNull();
    expect(screen.queryByRole("button", { name: "添加服务商" })).toBeNull();
  });

  it("shows a compact platform status line with link to providers", () => {
    mockProviders(
      providersResponse({
        providers: [],
        platform_available: true,
        platform_model: "deepseek-v4-flash",
        billing_mode: "platform",
        free_tier_active: true,
      }),
    );
    mockProfiles(
      profilesResponse({
        data: [
          {
            id: "sys-52",
            name: "5.2",
            kind: "system",
            is_default: true,
            main: {
              origin: "platform",
              provider_id: null,
              model: "deepseek-v4-flash",
            },
            worker: null,
            background: null,
          },
        ],
      }),
    );
    renderPage();
    expect(screen.getByText(/平台免费额度/)).toBeTruthy();
    expect(screen.getByRole("link", { name: "接入服务商" })).toBeTruthy();
    expect(screen.queryByText("平台额度")).toBeNull();
  });

  it("sets a user profile as the account default", async () => {
    vi.mocked(setDefaultLlmModelProfile).mockResolvedValue({
      id: "user-mine",
      name: "办公",
      kind: "user",
      is_default: true,
      main: { origin: "byok", provider_id: "p2", model: "gpt-4o" },
    });
    mockProviders(providersResponse());
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "设为默认" }));
    await waitFor(() =>
      expect(setDefaultLlmModelProfile).toHaveBeenCalledWith("user-mine"),
    );
  });

  it("copies a system preset into a user profile", async () => {
    vi.mocked(createLlmModelProfile).mockResolvedValue({
      id: "user-copy",
      name: "5.2 副本",
      kind: "user",
      is_default: false,
      main: { origin: "byok", provider_id: "p1", model: "deepseek-v4-pro" },
    });
    mockProviders(providersResponse());
    renderPage();
    fireEvent.click(screen.getAllByRole("button", { name: "复制" })[0]);
    await waitFor(() =>
      expect(createLlmModelProfile).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "5.2 副本",
          main: {
            origin: "byok",
            provider_id: "p1",
            model: "deepseek-v4-pro",
          },
          set_as_default: false,
        }),
      ),
    );
  });

  it("deletes a user profile after confirm", async () => {
    const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
    mockProviders(providersResponse());
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "删除" }));
    await waitFor(() =>
      expect(deleteLlmModelProfile).toHaveBeenCalledWith("user-mine"),
    );
    confirmSpy.mockRestore();
  });

  it("does not offer delete on system presets", () => {
    mockProviders(providersResponse());
    renderPage();
    expect(screen.getByText("5.2")).toBeTruthy();
    expect(screen.getByText("预置")).toBeTruthy();
    expect(screen.getAllByRole("button", { name: "删除" })).toHaveLength(1);
  });

  it("opens the create editor from 新建 with optional slots visible", () => {
    mockProviders(providersResponse());
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "新建" }));
    expect(screen.getByText("新建组合", { selector: "p" })).toBeTruthy();
    expect(screen.getByText("主模型（必填）")).toBeTruthy();
    expect(screen.getByText("Worker 模型")).toBeTruthy();
    expect(screen.getByText("后台任务模型")).toBeTruthy();
    expect(screen.getAllByText("跟随主模型").length).toBeGreaterThanOrEqual(2);
    expect(screen.getByText(/辩论用主模型/)).toBeTruthy();
    expect(screen.getByText(/标题、记忆等后台任务/)).toBeTruthy();
  });

  it("saves an edited user profile, toasts success, and closes the editor", async () => {
    vi.mocked(updateLlmModelProfile).mockResolvedValue({
      id: "user-mine",
      name: "办公",
      kind: "user",
      is_default: false,
      main: { origin: "byok", provider_id: "p2", model: "gpt-4o" },
      worker: null,
      background: null,
    });
    mockProviders(providersResponse());
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "编辑" }));
    expect(screen.getByText("编辑「办公」")).toBeTruthy();
    fireEvent.click(screen.getByRole("button", { name: "保存" }));
    await waitFor(() =>
      expect(updateLlmModelProfile).toHaveBeenCalledWith(
        "user-mine",
        expect.objectContaining({
          name: "办公",
          main: { origin: "byok", provider_id: "p2", model: "gpt-4o" },
        }),
      ),
    );
    await waitFor(() =>
      expect(notifySuccess).toHaveBeenCalledWith("已保存「办公」"),
    );
    expect(screen.queryByText("编辑「办公」")).toBeNull();
    expect(screen.getByRole("button", { name: "编辑" })).toBeTruthy();
  });

  it("shows combinations for keyless platform users", () => {
    useModelsMock.mockReturnValue({
      data: {
        byok_configured: false,
        current: { id: "platform-flash", origin: "platform" },
        models: [
          {
            id: "platform-flash",
            origin: "platform",
            display_name: "Flash (平台)",
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
    mockProviders(
      providersResponse({
        providers: [],
        platform_available: true,
        platform_model: "platform-flash",
        billing_mode: "platform",
        free_tier_active: true,
      }),
    );
    mockProfiles(
      profilesResponse({
        data: [
          {
            id: "sys-52",
            name: "5.2",
            kind: "system",
            is_default: true,
            main: {
              origin: "platform",
              provider_id: null,
              model: "platform-flash",
            },
            worker: null,
            background: null,
          },
        ],
      }),
    );
    renderPage();
    expect(screen.getByText("模型组合")).toBeTruthy();
    expect(screen.getByText("5.2")).toBeTruthy();
  });

  it("shows empty CTA to providers when byok has no providers or platform", () => {
    mockProviders(
      providersResponse({
        providers: [],
        platform_available: false,
        billing_mode: "byok",
      }),
    );
    renderPage();
    expect(screen.getByRole("button", { name: "接入服务商" })).toBeTruthy();
    expect(screen.queryByText("模型组合")).toBeNull();
  });

  it("on 新建 when seedMain fails shows providers guide link and does not open editor", () => {
    useModelsMock.mockReturnValue({
      data: {
        byok_configured: true,
        current: undefined,
        models: [],
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useModels>);
    mockProviders(
      providersResponse({
        providers: [
          {
            id: "p1",
            label: "DeepSeek",
            base_url: "https://api.deepseek.com/v1",
            default_model: "",
            status: "active",
            masked_key: "••••abcd",
            supports_tools: true,
          },
        ],
        platform_available: false,
      }),
    );
    mockProfiles(profilesResponse({ data: [] }));
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "新建" }));
    expect(screen.queryByText("新建组合", { selector: "p" })).toBeNull();
    const link = screen.getByRole("link", { name: "接入服务商" });
    expect(link.getAttribute("href")).toBe("/more/providers");
    expect(screen.getByText(/暂无可用模型/)).toBeTruthy();
  });

  it("when groups have no models, create editor shows providers guide and disables Worker/background", () => {
    // current 可 seedMain，但 provider 不在列表且无 catalog/default → groups.models 合计为空
    useModelsMock.mockReturnValue({
      data: {
        byok_configured: true,
        current: {
          id: "orphan-model",
          origin: "byok",
          provider_id: "gone-provider",
        },
        models: [],
      },
      isLoading: false,
      isError: false,
      refetch: vi.fn(),
    } as unknown as ReturnType<typeof useModels>);
    mockProviders(
      providersResponse({
        providers: [
          {
            id: "p1",
            label: "DeepSeek",
            base_url: "https://api.deepseek.com/v1",
            default_model: "",
            status: "active",
            masked_key: "••••abcd",
            supports_tools: true,
          },
        ],
        platform_available: false,
      }),
    );
    mockProfiles(profilesResponse({ data: [] }));
    renderPage();
    fireEvent.click(screen.getByRole("button", { name: "新建" }));
    expect(screen.getByText("新建组合", { selector: "p" })).toBeTruthy();
    const guide = screen.getByRole("link", { name: "接入服务商" });
    expect(guide.getAttribute("href")).toBe("/more/providers");
    expect(screen.getByText(/暂无可用模型/)).toBeTruthy();

    expect(document.getElementById("profile-worker")).toHaveProperty(
      "disabled",
      true,
    );
    expect(document.getElementById("profile-background")).toHaveProperty(
      "disabled",
      true,
    );
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
