import {
  PLATFORM_POINTER_ID,
  buildDefaultProviderGroups,
  decodePointer,
  encodePointer,
  pointerValue,
} from "@/lib/llmDefaults";
import type { ModelProfileSlot } from "@/services/llmModelProfiles";
import type { LlmProviderView } from "@/services/llmProviders";
import type { ModelCatalog, ModelCatalogItem } from "@/services/models";
import { describe, expect, it } from "vitest";

function provider(
  over: Partial<LlmProviderView> & { id: string },
): LlmProviderView {
  return {
    label: "",
    base_url: "https://api.example.com/v1",
    default_model: "model-default",
    status: "unchecked",
    ...over,
  };
}

function catalogItem(
  over: Partial<ModelCatalogItem> & { id: string },
): ModelCatalogItem {
  return {
    origin: "byok",
    display_name: over.id,
    vendor: "V",
    capabilities: [],
    available: true,
    provider_id: over.provider_id ?? "p1",
    ...over,
  };
}

function catalog(models: ModelCatalogItem[]): ModelCatalog {
  return {
    byok_configured: true,
    current: { id: models[0]?.id ?? "x", origin: "byok" },
    models,
  };
}

describe("encode/decode pointer", () => {
  it("round-trips a byok slot", () => {
    const slot: ModelProfileSlot = {
      origin: "byok",
      provider_id: "p1",
      model: "m1",
    };
    expect(decodePointer(encodePointer(slot))).toEqual(slot);
  });

  it("round-trips a platform slot", () => {
    const slot: ModelProfileSlot = {
      origin: "platform",
      provider_id: null,
      model: "flash",
    };
    expect(encodePointer(slot)).toBe(`${PLATFORM_POINTER_ID}::flash`);
    expect(decodePointer(encodePointer(slot))).toEqual(slot);
  });

  it("returns null for empty follow value", () => {
    expect(decodePointer("")).toBeNull();
    expect(pointerValue(null)).toBe("");
  });
});

describe("buildDefaultProviderGroups", () => {
  it("groups byok models under their provider and pins platform first", () => {
    const groups = buildDefaultProviderGroups(
      [
        provider({
          id: "p1",
          label: "DeepSeek",
          default_model: "deepseek-v4-pro",
        }),
        provider({ id: "p2", label: "OpenAI", default_model: "gpt-4o" }),
      ],
      catalog([
        catalogItem({
          id: "platform-flash",
          origin: "platform",
          display_name: "Flash",
          provider_id: null,
        }),
        catalogItem({
          id: "deepseek-v4-pro",
          provider_id: "p1",
          display_name: "DeepSeek V4 Pro",
        }),
        catalogItem({
          id: "gpt-4o",
          provider_id: "p2",
          display_name: "GPT-4o",
        }),
      ]),
    );
    expect(groups[0].providerLabel).toBe("平台额度");
    expect(groups[0].models.map((m) => m.model)).toEqual(["platform-flash"]);
    expect(groups.map((g) => g.providerLabel)).toContain("DeepSeek");
    expect(groups.map((g) => g.providerLabel)).toContain("OpenAI");
  });

  it("folds live slot models into their group", () => {
    const groups = buildDefaultProviderGroups(
      [
        provider({
          id: "p1",
          label: "DeepSeek",
          default_model: "deepseek-v4-pro",
        }),
      ],
      catalog([
        catalogItem({
          id: "deepseek-v4-pro",
          provider_id: "p1",
          display_name: "DeepSeek V4 Pro",
        }),
      ]),
      {
        origin: "byok",
        provider_id: "p1",
        model: "custom-model",
      },
    );
    expect(groups[0].models.map((m) => m.model)).toContain("custom-model");
    expect(groups[0].models.map((m) => m.model)).toContain("deepseek-v4-pro");
  });

  it("creates a platform group when only a live platform slot exists", () => {
    const groups = buildDefaultProviderGroups([], catalog([]), {
      origin: "platform",
      provider_id: null,
      model: "custom-platform",
    });
    expect(groups[0].providerId).toBe(PLATFORM_POINTER_ID);
    expect(groups[0].models.map((m) => m.model)).toEqual(["custom-platform"]);
  });
});
