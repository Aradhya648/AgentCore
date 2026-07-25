// @vitest-environment jsdom
/**
 * Render + interaction tests for the mobile 会话级模型组合 selector (ModelPicker).
 */
import type { LlmModelProfileListResponse } from "@/api/modelProfiles";
import type { ModelCatalog } from "@/api/models";
import { ModelPicker } from "@/components/ModelPicker";
import { MODEL_CONFIG_PATH } from "@/lib/errors";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/components/Modal", () => ({
  Modal: ({ children }: { children: ReactNode }) => <div>{children}</div>,
}));

const mockNavigate = vi.fn();
vi.mock("react-router-dom", async () => {
  const actual =
    await vi.importActual<typeof import("react-router-dom")>(
      "react-router-dom",
    );
  return { ...actual, useNavigate: () => mockNavigate };
});

const PROFILES: LlmModelProfileListResponse = {
  default_model_profile_id: "00000000-0000-4000-8000-000000000011",
  data: [
    {
      id: "00000000-0000-4000-8000-000000000011",
      name: "5.2",
      kind: "system",
      main: { origin: "platform", model: "5.2", provider_id: null },
      worker: null,
      background: null,
      is_default: true,
    },
    {
      id: "prof-user-1",
      name: "写作强档",
      kind: "user",
      main: {
        origin: "byok",
        model: "deepseek-v4-pro",
        provider_id: "prov-deepseek",
      },
      worker: {
        origin: "byok",
        model: "gpt-4o",
        provider_id: "prov-openai",
      },
      background: null,
      is_default: false,
    },
    {
      id: "prof-implicit",
      name: "隐式组合",
      kind: "implicit",
      main: { origin: "platform", model: "platform-flash", provider_id: null },
      worker: null,
      background: null,
      is_default: false,
    },
  ],
};

const CATALOG: ModelCatalog = {
  byok_configured: true,
  current: {
    id: "deepseek-v4-pro",
    origin: "byok",
    provider_id: "prov-deepseek",
  },
  models: [
    {
      id: "5.2",
      origin: "platform",
      display_name: "5.2",
      vendor: "Platform",
      capabilities: [],
      context_length: null,
      price: null,
      available: true,
    },
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

vi.mock("@/api/modelProfiles", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/api/modelProfiles")>();
  return {
    ...actual,
    useModelProfiles: () => ({
      data: PROFILES,
      loading: false,
      error: null,
      refetch: vi.fn(),
    }),
  };
});

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

afterEach(() => {
  cleanup();
  mockNavigate.mockReset();
});

describe("ModelPicker (mobile profiles)", () => {
  it("lists combinations with 主 · Worker summary and hides implicit profiles", () => {
    render(
      <ModelPicker
        conversationProfileId={null}
        onSelect={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByText("选择模型组合")).toBeTruthy();
    expect(screen.getByText("5.2")).toBeTruthy();
    expect(screen.getByText("写作强档")).toBeTruthy();
    expect(screen.getByText("5.2 · 跟随主模型")).toBeTruthy();
    expect(screen.getByText("DeepSeek V4 Pro · GPT-4o")).toBeTruthy();
    expect(screen.queryByText("隐式组合")).toBeNull();
    expect(screen.queryByText("跟随账号默认")).toBeNull();
  });

  it("highlights the account default when the conversation has no override", () => {
    render(
      <ModelPicker
        conversationProfileId={null}
        onSelect={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    expect(
      screen.getByTestId("profile-row-00000000-0000-4000-8000-000000000011")
        .className,
    ).toContain("model-row-selected");
  });

  it("selects a concrete profile id", () => {
    const onSelect = vi.fn();
    render(
      <ModelPicker
        conversationProfileId={null}
        onSelect={onSelect}
        onClose={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByTestId("profile-row-prof-user-1"));
    expect(onSelect).toHaveBeenCalledWith("prof-user-1");
  });

  it("offers 跟随账号默认 to clear an override", () => {
    const onSelect = vi.fn();
    render(
      <ModelPicker
        conversationProfileId="prof-user-1"
        onSelect={onSelect}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByTestId("profile-row-prof-user-1").className).toContain(
      "model-row-selected",
    );
    fireEvent.click(screen.getByTestId("profile-row-follow-default"));
    expect(onSelect).toHaveBeenCalledWith(null);
  });

  it("routes 管理组合 to 模型配置", () => {
    const onClose = vi.fn();
    render(
      <ModelPicker
        conversationProfileId={null}
        onSelect={vi.fn()}
        onClose={onClose}
      />,
    );
    fireEvent.click(screen.getByTestId("profile-manage"));
    expect(onClose).toHaveBeenCalled();
    expect(mockNavigate).toHaveBeenCalledWith(MODEL_CONFIG_PATH);
  });
});
