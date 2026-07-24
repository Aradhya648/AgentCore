import {
  BYOK_PROVIDER_PRESETS,
  DEFAULT_BYOK_PROVIDER_ID,
  getByokProviderPreset,
  normalizeByokBaseUrl,
  resolveByokProviderFromConfig,
} from "@/lib/byokProviderPresets";
import { describe, expect, it } from "vitest";

describe("normalizeByokBaseUrl", () => {
  it("lowercases and strips trailing slashes", () => {
    expect(normalizeByokBaseUrl("HTTPS://API.OpenAI.com/v1/")).toBe(
      "https://api.openai.com/v1",
    );
  });
});

describe("resolveByokProviderFromConfig", () => {
  it("defaults empty base_url to DeepSeek preset", () => {
    expect(resolveByokProviderFromConfig("")).toBe(DEFAULT_BYOK_PROVIDER_ID);
    expect(DEFAULT_BYOK_PROVIDER_ID).toBe("deepseek");
  });

  it("matches canonical preset base_url", () => {
    expect(resolveByokProviderFromConfig("https://api.openai.com/v1")).toBe(
      "openai",
    );
    expect(
      resolveByokProviderFromConfig("https://open.bigmodel.cn/api/paas/v4"),
    ).toBe("zhipu");
  });

  it("matches aliases (DeepSeek /v1, Moonshot international)", () => {
    expect(resolveByokProviderFromConfig("https://api.deepseek.com/v1")).toBe(
      "deepseek",
    );
    expect(resolveByokProviderFromConfig("https://api.moonshot.ai/v1")).toBe(
      "moonshot",
    );
  });

  it("falls back to custom for unknown endpoints", () => {
    expect(resolveByokProviderFromConfig("https://my-proxy.example/v1")).toBe(
      "custom",
    );
  });

  it("treats trailing slash variants as the same preset", () => {
    expect(resolveByokProviderFromConfig("https://api.deepseek.com/")).toBe(
      "deepseek",
    );
  });
});

describe("getByokProviderPreset", () => {
  it("returns DeepSeek flash-first metadata", () => {
    const preset = getByokProviderPreset("deepseek");
    expect(preset.baseUrl).toBe("https://api.deepseek.com");
    expect(preset.defaultModel).toBe("deepseek-v4-flash");
    expect(preset.models).toEqual(["deepseek-v4-flash", "deepseek-v4-pro"]);
    expect(preset.models).not.toContain("deepseek-chat");
  });

  it("lists DeepSeek first among vendor presets", () => {
    expect(BYOK_PROVIDER_PRESETS[0]?.id).toBe("deepseek");
  });
});
