// @vitest-environment jsdom
/**
 * Unit tests for the mobile model-catalog helpers: the 当前模型 badge label resolution and
 * the 新对话继承上次选择 last-used memory (localStorage-backed, best-effort). Covers the
 * multi-provider (id, origin, provider_id) pick upgrade.
 */
import type { ModelCatalog } from "@/api/models";
import {
  clearLastModel,
  conversationModelPick,
  getLastModel,
  modelDisplayLabel,
  setLastModel,
} from "@/api/models";
import { afterEach, describe, expect, it } from "vitest";

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
      id: "deepseek-v4-pro",
      origin: "platform",
      provider_id: null,
      provider_label: null,
      display_name: "DeepSeek V4 Pro (平台)",
      vendor: "DeepSeek",
      capabilities: [],
      context_length: null,
      price: null,
      available: true,
    },
  ],
};

afterEach(() => {
  clearLastModel();
});

describe("modelDisplayLabel", () => {
  it("maps an override (id, origin) to its catalog display name", () => {
    expect(
      modelDisplayLabel(CATALOG, { id: "deepseek-v4-pro", origin: "byok" }),
    ).toBe("DeepSeek V4 Pro");
    expect(
      modelDisplayLabel(CATALOG, {
        id: "deepseek-v4-pro",
        origin: "platform",
      }),
    ).toBe("DeepSeek V4 Pro (平台)");
  });

  it("falls back to the account model (catalog.current) with no override", () => {
    expect(modelDisplayLabel(CATALOG, null)).toBe("DeepSeek V4 Pro");
  });

  it("returns the raw id for an id not in the catalog", () => {
    expect(
      modelDisplayLabel(CATALOG, { id: "mystery-model", origin: "byok" }),
    ).toBe("mystery-model");
  });

  it("returns null when nothing is known yet", () => {
    expect(modelDisplayLabel(null, null)).toBeNull();
  });
});

describe("conversationModelPick", () => {
  it("builds a pick from conversation fields", () => {
    expect(conversationModelPick("gpt-4o", "platform")).toEqual({
      id: "gpt-4o",
      origin: "platform",
    });
    expect(conversationModelPick("gpt-4o", null)).toEqual({
      id: "gpt-4o",
      origin: "byok",
    });
    expect(conversationModelPick(null, "platform")).toBeNull();
  });

  it("tags the BYOK provider when one is present", () => {
    expect(
      conversationModelPick("deepseek-v4-pro", "byok", "prov-deepseek"),
    ).toEqual({
      id: "deepseek-v4-pro",
      origin: "byok",
      providerId: "prov-deepseek",
    });
    // A platform pick never carries a providerId even if one is (spuriously) passed.
    expect(conversationModelPick("gpt-4o", "platform", "prov-x")).toEqual({
      id: "gpt-4o",
      origin: "platform",
    });
  });
});

describe("last-used model (新对话继承上次选择)", () => {
  it("round-trips a concrete (id, origin) pick and clears back to null", () => {
    expect(getLastModel()).toBeNull();
    setLastModel({ id: "gpt-4o", origin: "platform" });
    expect(getLastModel()).toEqual({ id: "gpt-4o", origin: "platform" });
    clearLastModel();
    expect(getLastModel()).toBeNull();
  });

  it("round-trips a BYOK pick with its provider_id", () => {
    setLastModel({
      id: "deepseek-v4-pro",
      origin: "byok",
      providerId: "prov-deepseek",
    });
    expect(getLastModel()).toEqual({
      id: "deepseek-v4-pro",
      origin: "byok",
      providerId: "prov-deepseek",
    });
  });

  it("discards legacy plain-id records", () => {
    localStorage.setItem("agentcore.mobile.lastModel", "legacy-id-only");
    expect(getLastModel()).toBeNull();
  });
});
