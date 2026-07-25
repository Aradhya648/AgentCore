import type { ModelProfileSlot } from "@/services/llmModelProfiles";
import type { LlmProviderView } from "@/services/llmProviders";
import type { ModelCatalog } from "@/services/models";

/**
 * 模型组合槽位选择器的纯逻辑（设置·模型配置 · 编辑组合）。
 *
 * 槽位是 `(model, origin, provider_id)` 指针。选择器按服务商分组呈现 BYOK 候选，
 * 并在平台可用时追加「平台额度」分组；每个服务商的候选 = 其 `default_model` ∪
 * 模型目录里该服务商带出的模型；再把当前槽位模型并入，保证现值始终可选。
 */

export type DefaultModelOption = { model: string; label: string };
export type DefaultProviderGroup = {
  providerId: string;
  providerLabel: string;
  models: DefaultModelOption[];
};

const SEP = "::";
/**
 * Select-value / optgroup id for platform-catalog pointers (not a real provider UUID).
 */
export const PLATFORM_POINTER_ID = "__platform__";

/** Encode a `(provider_id|__platform__, model)` pair or a full slot into a select value. */
export function encodePointer(
  providerIdOrSlot: string | ModelProfileSlot,
  model?: string,
): string {
  if (typeof providerIdOrSlot === "string") {
    return `${providerIdOrSlot}${SEP}${model ?? ""}`;
  }
  const p = providerIdOrSlot;
  if (p.origin === "platform" || !p.provider_id) {
    return `${PLATFORM_POINTER_ID}${SEP}${p.model}`;
  }
  return `${p.provider_id}${SEP}${p.model}`;
}

/** The `<select>` value for a slot (empty string = 未设置 / 跟随). */
export function pointerValue(
  slot: ModelProfileSlot | null | undefined,
): string {
  if (!slot?.model) return "";
  return encodePointer(slot);
}

/** Parse a `<select>` option value back into a slot (null for the empty value). */
export function decodePointer(value: string): ModelProfileSlot | null {
  const idx = value.indexOf(SEP);
  if (idx < 0) return null;
  const provider_id = value.slice(0, idx);
  const model = value.slice(idx + SEP.length);
  if (!provider_id || !model) return null;
  if (provider_id === PLATFORM_POINTER_ID) {
    return { origin: "platform", provider_id: null, model };
  }
  return { origin: "byok", provider_id, model };
}

/**
 * Build the per-provider option groups for slot selectors.
 * Includes a 「平台额度」 group when the catalog exposes available `origin=platform` rows.
 * `slots` are currently-set pointers — their models are folded into the matching group.
 */
export function buildDefaultProviderGroups(
  providers: LlmProviderView[],
  catalog: ModelCatalog | undefined,
  ...slots: (ModelProfileSlot | null | undefined)[]
): DefaultProviderGroup[] {
  const groups: DefaultProviderGroup[] = providers.map((p) => {
    const models: DefaultModelOption[] = [];
    const seen = new Set<string>();
    const add = (model: string, label?: string | null) => {
      const m = model.trim();
      if (!m || seen.has(m)) return;
      seen.add(m);
      models.push({ model: m, label: label?.trim() || m });
    };
    for (const item of catalog?.models ?? []) {
      if (item.origin === "byok" && item.provider_id === p.id) {
        add(item.id, item.display_name);
      }
    }
    if (p.default_model) add(p.default_model);
    return {
      providerId: p.id,
      providerLabel: p.label?.trim() || p.base_url,
      models,
    };
  });

  const platformModels: DefaultModelOption[] = [];
  const platformSeen = new Set<string>();
  for (const item of catalog?.models ?? []) {
    if (item.origin !== "platform" || item.available === false) continue;
    const m = item.id.trim();
    if (!m || platformSeen.has(m)) continue;
    platformSeen.add(m);
    platformModels.push({
      model: m,
      label: item.display_name?.trim() || m,
    });
  }
  if (platformModels.length > 0) {
    groups.unshift({
      providerId: PLATFORM_POINTER_ID,
      providerLabel: "平台额度",
      models: platformModels,
    });
  }

  for (const slot of slots) {
    if (!slot?.model) continue;
    const groupId =
      slot.origin === "platform" || !slot.provider_id
        ? PLATFORM_POINTER_ID
        : slot.provider_id;
    let group = groups.find((g) => g.providerId === groupId);
    if (!group && groupId === PLATFORM_POINTER_ID) {
      group = {
        providerId: PLATFORM_POINTER_ID,
        providerLabel: "平台额度",
        models: [],
      };
      groups.unshift(group);
    }
    if (group && !group.models.some((m) => m.model === slot.model)) {
      group.models.unshift({ model: slot.model, label: slot.model });
    }
  }
  return groups;
}
