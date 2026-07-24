import {
  buildDefaultProviderGroups,
  decodePointer,
  encodePointer,
  pointerValue,
} from "@/lib/llmDefaults";
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
    is_default_chat: false,
    is_default_background: false,
    ...over,
  };
}

function catalogItem(
  over: Partial<ModelCatalogItem> & { id: string; provider_id: string },
): ModelCatalogItem {
  return {
    origin: "byok",
    display_name: over.id,
    vendor: "V",
    capabilities: [],
    available: true,
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
  it("round-trips a provider+model pointer", () => {
    const v = encodePointer("prov-1", "deepseek-v4-pro");
    expect(v).toBe("prov-1::deepseek-v4-pro");
    expect(decodePointer(v)).toEqual({
      provider_id: "prov-1",
      model: "deepseek-v4-pro",
    });
  });

  it("splits on the first separator so model names may contain colons", () => {
    const v = encodePointer("prov-1", "org/model:tag");
    expect(decodePointer(v)).toEqual({
      provider_id: "prov-1",
      model: "org/model:tag",
    });
  });

  it("treats the empty value as no pointer", () => {
    expect(pointerValue(null)).toBe("");
    expect(pointerValue(undefined)).toBe("");
    expect(decodePointer("")).toBeNull();
  });

  it("encodes a live pointer for the select value", () => {
    expect(pointerValue({ provider_id: "p", model: "m" })).toBe("p::m");
  });
});

describe("buildDefaultProviderGroups", () => {
  it("groups per provider: default_model unioned with that provider's catalog models", () => {
    const providers = [
      provider({
        id: "p1",
        label: "DeepSeek",
        default_model: "deepseek-v4-pro",
      }),
      provider({ id: "p2", label: "OpenAI", default_model: "gpt-4o" }),
    ];
    const models = [
      catalogItem({
        id: "deepseek-v4-pro",
        provider_id: "p1",
        display_name: "DeepSeek V4 Pro",
      }),
      catalogItem({
        id: "deepseek-v4-flash",
        provider_id: "p1",
        display_name: "DeepSeek V4 Flash",
      }),
      catalogItem({ id: "gpt-4o", provider_id: "p2" }),
      // Another provider's / platform rows are ignored for a provider's group.
      catalogItem({ id: "ghost", provider_id: "p9" }),
    ];

    const groups = buildDefaultProviderGroups(providers, catalog(models));

    expect(groups.map((g) => g.providerLabel)).toEqual(["DeepSeek", "OpenAI"]);
    expect(groups[0].models.map((m) => m.model)).toEqual([
      "deepseek-v4-pro",
      "deepseek-v4-flash",
    ]);
    expect(groups[0].models[0].label).toBe("DeepSeek V4 Pro");
    expect(groups[1].models.map((m) => m.model)).toEqual(["gpt-4o"]);
  });

  it("folds a live pointer's model into its group even if the catalog lacks it", () => {
    const providers = [
      provider({ id: "p1", default_model: "deepseek-v4-pro" }),
    ];
    const groups = buildDefaultProviderGroups(providers, catalog([]), {
      provider_id: "p1",
      model: "custom-model",
    });
    expect(groups[0].models.map((m) => m.model)).toContain("custom-model");
    expect(groups[0].models.map((m) => m.model)).toContain("deepseek-v4-pro");
  });

  it("falls back to base_url as the group label when no label is set", () => {
    const groups = buildDefaultProviderGroups(
      [provider({ id: "p1", label: "", base_url: "https://host.example/v1" })],
      undefined,
    );
    expect(groups[0].providerLabel).toBe("https://host.example/v1");
  });
});
