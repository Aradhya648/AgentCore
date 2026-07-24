// @vitest-environment jsdom
/**
 * Render + interaction tests for the mobile 会话级模型切换 selector (ModelPicker).
 *
 * The native <dialog> shell (Modal) is stubbed to a passthrough — jsdom has no showModal —
 * so these assertions focus on the picker's own logic: origin grouping, BYOK sub-grouping by
 * SERVICE PROVIDER (provider_label), capability/price hints, the greyed unavailable → 模型配置
 * route, (id, origin, provider_id) selection, and the 跟随账号默认 clear row.
 */
import type { ModelCatalog } from "@/api/models";
import { ModelPicker } from "@/components/ModelPicker";
import { MODEL_CONFIG_PATH } from "@/lib/errors";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
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
      capabilities: ["tools", "reasoning"],
      context_length: 128000,
      price: { cache_hit: "0.1", cache_miss: "0.28", output: "0.42" },
      available: true,
    },
    {
      id: "deepseek-v4-flash",
      origin: "byok",
      provider_id: "prov-deepseek",
      provider_label: "DeepSeek",
      display_name: "DeepSeek V4 Flash",
      vendor: "DeepSeek",
      capabilities: ["tools"],
      context_length: 64000,
      price: null,
      available: true,
    },
    {
      id: "deepseek-v4-pro",
      origin: "platform",
      provider_id: null,
      provider_label: null,
      display_name: "DeepSeek V4 Pro",
      vendor: "DeepSeek",
      capabilities: ["tools", "reasoning"],
      context_length: 128000,
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
      capabilities: ["vision", "tools"],
      context_length: 128000,
      price: null,
      available: false,
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

afterEach(() => {
  cleanup();
  mockNavigate.mockReset();
});

describe("ModelPicker (mobile)", () => {
  it("groups models by origin then service provider with capability, context and price hints", () => {
    render(
      <ModelPicker
        conversationModel={null}
        onSelect={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    expect(screen.getByText("自带 Key")).toBeTruthy();
    expect(screen.getByText("平台模型")).toBeTruthy();
    // BYOK sub-grouped by provider_label; the OpenAI provider group heading is present.
    expect(screen.getByText("OpenAI")).toBeTruthy();
    expect(screen.getAllByText("DeepSeek").length).toBeGreaterThanOrEqual(1);
    const proRow = within(
      screen.getByTestId("model-row-deepseek-v4-pro-byok-prov-deepseek"),
    );
    expect(proRow.getByText("DeepSeek V4 Pro")).toBeTruthy();
    expect(proRow.getByText("工具")).toBeTruthy();
    expect(proRow.getByText("推理")).toBeTruthy();
    expect(proRow.getByText("128K 上下文")).toBeTruthy();
    expect(proRow.getByText("输入 $0.28 / 输出 $0.42 /1M")).toBeTruthy();
    expect(
      within(
        screen.getByTestId("model-row-deepseek-v4-pro-platform"),
      ).getByText("平台额度"),
    ).toBeTruthy();
  });

  it("highlights the account model (by provider) when the conversation has no override", () => {
    render(
      <ModelPicker
        conversationModel={null}
        onSelect={vi.fn()}
        onClose={vi.fn()}
      />,
    );
    expect(
      screen.getByTestId("model-row-deepseek-v4-pro-byok-prov-deepseek")
        .className,
    ).toContain("model-row-selected");
    expect(screen.queryByText("跟随账号默认模型")).toBeNull();
  });

  it("selects an available model by (id, origin, provider_id)", () => {
    const onSelect = vi.fn();
    render(
      <ModelPicker
        conversationModel={null}
        onSelect={onSelect}
        onClose={vi.fn()}
      />,
    );
    fireEvent.click(
      screen.getByTestId("model-row-deepseek-v4-flash-byok-prov-deepseek"),
    );
    expect(onSelect).toHaveBeenCalledWith({
      id: "deepseek-v4-flash",
      origin: "byok",
      providerId: "prov-deepseek",
    });
  });

  it("routes an unavailable model to 模型配置 instead of selecting it", () => {
    const onSelect = vi.fn();
    const onClose = vi.fn();
    render(
      <ModelPicker
        conversationModel={null}
        onSelect={onSelect}
        onClose={onClose}
      />,
    );
    const locked = screen.getByTestId("model-row-gpt-4o-byok-prov-openai");
    expect(locked.className).toContain("model-row-disabled");
    expect(screen.getByText("需配置 API Key · 去配置")).toBeTruthy();
    fireEvent.click(locked);
    expect(onSelect).not.toHaveBeenCalled();
    expect(onClose).toHaveBeenCalled();
    expect(mockNavigate).toHaveBeenCalledWith(MODEL_CONFIG_PATH);
  });

  it("offers 跟随账号默认 to clear an override and highlights the override row", () => {
    const onSelect = vi.fn();
    render(
      <ModelPicker
        conversationModel={{
          id: "deepseek-v4-flash",
          origin: "byok",
          providerId: "prov-deepseek",
        }}
        onSelect={onSelect}
        onClose={vi.fn()}
      />,
    );
    expect(
      screen.getByTestId("model-row-deepseek-v4-flash-byok-prov-deepseek")
        .className,
    ).toContain("model-row-selected");
    fireEvent.click(screen.getByText("跟随账号默认模型"));
    expect(onSelect).toHaveBeenCalledWith(null);
  });
});
