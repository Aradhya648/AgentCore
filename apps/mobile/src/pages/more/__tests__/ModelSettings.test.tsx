// @vitest-environment jsdom
/**
 * Render + interaction tests for 设置·模型配置 — providers + 模型组合 section.
 */
import type { LlmProvidersResponse } from "@/api/llmProviders";
import {
  deleteLlmProvider,
  listLlmProviders,
  testLlmProvider,
} from "@/api/llmProviders";
import type { LlmModelProfileView } from "@/api/modelProfiles";
import {
  createModelProfile,
  deleteModelProfile,
  listModelProfiles,
  setDefaultModelProfile,
  updateModelProfile,
} from "@/api/modelProfiles";
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
  testLlmProvider: vi.fn(),
  deleteLlmProvider: vi.fn(),
  createLlmProvider: vi.fn(),
  updateLlmProvider: vi.fn(),
}));

vi.mock("@/api/modelProfiles", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/modelProfiles")>();
  return {
    ...actual,
    listModelProfiles: vi.fn(),
    createModelProfile: vi.fn(),
    updateModelProfile: vi.fn(),
    deleteModelProfile: vi.fn(),
    setDefaultModelProfile: vi.fn(),
  };
});

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
      id: "platform-flash",
      origin: "platform",
      display_name: "Flash (平台)",
      vendor: "Platform",
      capabilities: [],
      context_length: null,
      price: null,
      available: true,
    },
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
const mockListProfiles = vi.mocked(listModelProfiles);
const mockSetDefault = vi.mocked(setDefaultModelProfile);
const mockCreateProfile = vi.mocked(createModelProfile);
vi.mocked(testLlmProvider);
vi.mocked(deleteLlmProvider);
vi.mocked(deleteModelProfile);
vi.mocked(updateModelProfile);

const SYSTEM_52: LlmModelProfileView = {
  id: "00000000-0000-4000-8000-000000000011",
  name: "5.2",
  kind: "system",
  main: { origin: "platform", model: "5.2", provider_id: null },
  worker: null,
  background: null,
  is_default: true,
};

const USER_PROFILE: LlmModelProfileView = {
  id: "prof-user-1",
  name: "写作强档",
  kind: "user",
  main: {
    origin: "byok",
    model: "deepseek-v4-pro",
    provider_id: "prov-deepseek",
  },
  worker: { origin: "byok", model: "gpt-4o", provider_id: "prov-openai" },
  background: null,
  is_default: false,
};

function makeProviders(
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
        masked_key: "sk-…abcd",
        supports_tools: true,
      },
      {
        id: "prov-openai",
        label: "OpenAI",
        base_url: "https://api.openai.com/v1",
        default_model: "gpt-4o",
        status: "unchecked",
        masked_key: "sk-…wxyz",
      },
    ],
    billing_mode: "platform",
    platform_available: true,
    platform_model: "deepseek-v4-pro",
    free_tier_active: false,
    ...overrides,
  };
}

function stubProfiles(data: LlmModelProfileView[], defaultId?: string | null) {
  mockListProfiles.mockResolvedValue({
    data,
    default_model_profile_id: defaultId ?? data.find((p) => p.is_default)?.id,
  });
}

afterEach(cleanup);
beforeEach(() => {
  mockList.mockReset();
  mockListProfiles.mockReset();
  mockSetDefault.mockReset();
  mockCreateProfile.mockReset();
});

describe("ModelSettings (profiles + providers)", () => {
  it("renders provider cards and the model-profiles section", async () => {
    mockList.mockResolvedValue(makeProviders());
    stubProfiles([SYSTEM_52, USER_PROFILE], SYSTEM_52.id);
    render(<ModelSettings />);

    await waitFor(() => expect(screen.getByText("DeepSeek")).toBeTruthy());
    expect(screen.getByText("OpenAI")).toBeTruthy();
    expect(screen.getByText("api.deepseek.com")).toBeTruthy();
    expect(screen.getByText("模型 deepseek-v4-pro")).toBeTruthy();
    expect(screen.getAllByTestId("provider-card")).toHaveLength(2);
    expect(screen.getByTestId("profiles-section")).toBeTruthy();
    expect(screen.getByText("5.2")).toBeTruthy();
    expect(screen.getByText("写作强档")).toBeTruthy();
    expect(screen.getByText("账号默认")).toBeTruthy();
    expect(screen.getByText("DeepSeek V4 Pro · GPT-4o")).toBeTruthy();
  });

  it("shows the platform-credit note when the deployment offers platform models", async () => {
    mockList.mockResolvedValue(makeProviders());
    stubProfiles([SYSTEM_52], SYSTEM_52.id);
    render(<ModelSettings />);
    await waitFor(() =>
      expect(screen.getByText(/不接入也可用平台额度直接对话/)).toBeTruthy(),
    );
  });

  it("sets the account default combination", async () => {
    mockList.mockResolvedValue(makeProviders());
    stubProfiles([SYSTEM_52, USER_PROFILE], SYSTEM_52.id);
    mockSetDefault.mockResolvedValue({ ...USER_PROFILE, is_default: true });
    render(<ModelSettings />);

    await waitFor(() => expect(screen.getByText("写作强档")).toBeTruthy());
    fireEvent.click(screen.getByText("设为默认"));
    await waitFor(() =>
      expect(mockSetDefault).toHaveBeenCalledWith(USER_PROFILE.id),
    );
  });

  it("opens the new-profile form and creates a combination", async () => {
    mockList.mockResolvedValue(makeProviders());
    stubProfiles([SYSTEM_52], SYSTEM_52.id);
    mockCreateProfile.mockResolvedValue(USER_PROFILE);
    render(<ModelSettings />);

    await waitFor(() => expect(screen.getByTestId("profile-new")).toBeTruthy());
    fireEvent.click(screen.getByTestId("profile-new"));

    const name = (await screen.findByLabelText("名称")) as HTMLInputElement;
    fireEvent.change(name, { target: { value: "写作强档" } });
    fireEvent.change(screen.getByLabelText("主模型"), {
      target: { value: "prov-deepseek::deepseek-v4-pro" },
    });
    fireEvent.click(screen.getByText("保存"));

    await waitFor(() =>
      expect(mockCreateProfile).toHaveBeenCalledWith({
        name: "写作强档",
        main: {
          origin: "byok",
          provider_id: "prov-deepseek",
          model: "deepseek-v4-pro",
        },
        worker: null,
        background: null,
        set_as_default: false,
      }),
    );
  });

  it("does not offer edit/delete on system presets", async () => {
    mockList.mockResolvedValue(makeProviders());
    stubProfiles([SYSTEM_52], SYSTEM_52.id);
    render(<ModelSettings />);

    await waitFor(() =>
      expect(screen.getByTestId(`profile-card-${SYSTEM_52.id}`)).toBeTruthy(),
    );
    const card = screen.getByTestId(`profile-card-${SYSTEM_52.id}`);
    expect(card.textContent).toContain("预置");
    expect(card.textContent).not.toContain("编辑");
    expect(card.textContent).not.toContain("删除");
  });

  it("surfaces ADMIN_PRODUCT_FORBIDDEN instead of a generic load failure", async () => {
    mockList.mockRejectedValue(
      new Error("此账号为管理员账号，请使用管理后台登录"),
    );
    stubProfiles([]);
    render(<ModelSettings />);
    await waitFor(() =>
      expect(
        screen.getByText("此账号为管理员账号，请使用管理后台登录"),
      ).toBeTruthy(),
    );
    expect(screen.queryByText("加载失败，请重试")).toBeNull();
  });
});
