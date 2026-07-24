import type {
  LlmDefaultPointer,
  LlmProviderView,
} from "@/services/llmProviders";
import type { ModelCatalog } from "@/services/models";

/**
 * 账号「聊天默认 / 后台默认」跨服务商选择器的纯逻辑（设置·模型配置）。
 *
 * 账号默认是一个 `(provider_id, model)` 指针（可跨服务商）。选择器**按服务商分组**呈现候选模型：
 * 每个服务商的候选 = 其 `default_model` ∪ 模型目录里该服务商（`origin=byok` ∧ `provider_id` 命中）
 * 带出的模型；再把当前生效指针的模型并入（即便目录尚未发现），保证现值始终可选。
 */

export type DefaultModelOption = { model: string; label: string };
export type DefaultProviderGroup = {
  providerId: string;
  providerLabel: string;
  models: DefaultModelOption[];
};

const SEP = "::";

/** Encode a `(provider_id, model)` pointer into a `<select>` option value. */
export function encodePointer(providerId: string, model: string): string {
  return `${providerId}${SEP}${model}`;
}

/** The `<select>` value for a pointer (empty string = 未设置 / 跟随). */
export function pointerValue(
  pointer: LlmDefaultPointer | null | undefined,
): string {
  return pointer ? encodePointer(pointer.provider_id, pointer.model) : "";
}

/** Parse a `<select>` option value back into a pointer (null for the empty value). */
export function decodePointer(value: string): LlmDefaultPointer | null {
  const idx = value.indexOf(SEP);
  if (idx < 0) return null;
  const provider_id = value.slice(0, idx);
  const model = value.slice(idx + SEP.length);
  if (!provider_id || !model) return null;
  return { provider_id, model };
}

/**
 * Build the per-provider option groups for the account default selectors.
 * `pointers` are the currently-set chat / background指针 — their models are folded
 * into the matching group so the live selection always renders as a valid option.
 */
export function buildDefaultProviderGroups(
  providers: LlmProviderView[],
  catalog: ModelCatalog | undefined,
  ...pointers: (LlmDefaultPointer | null | undefined)[]
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
    // Catalog rows first so their display names win; then the provider's own
    // default_model as a fallback (covers a freshly added / untested provider).
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

  for (const pointer of pointers) {
    if (!pointer?.model) continue;
    const group = groups.find((g) => g.providerId === pointer.provider_id);
    if (group && !group.models.some((m) => m.model === pointer.model)) {
      group.models.unshift({ model: pointer.model, label: pointer.model });
    }
  }
  return groups;
}
