import { uiGet, uiSet } from "@/lib/uiStorage";
import { api } from "@/services/api";
import type { components } from "@/types/api.generated";

/**
 * 会话级模型切换的目录数据层（模型目录 + 会话模型）。
 *
 * 聊天里的模型切换**只**以 `GET /v1/users/me/models` 目录为数据源（配置期表单另走
 * `byokProviderPresets` 的厂商硬编码清单）——目录混排 BYOK 与平台模型，UI 按来源分组、
 * 置灰与引导。选择键为 `(id, origin)` 对。REST 类型由后端 OpenAPI 生成（`pnpm gen:types`）。
 */

type Schemas = components["schemas"];

/** 目录响应：账号默认、BYOK 是否已配置、可选模型清单。 */
export type ModelCatalog = Schemas["ModelCatalogResponse"];
/** 目录里的一个模型（可选或置灰）。 */
export type ModelCatalogItem = Schemas["ModelCatalogItem"];
/** 账号当前解析出的默认模型。 */
export type ModelCatalogCurrent = Schemas["ModelCatalogCurrent"];
/** 复用的单价卡（USD 每百万 token，字符串；金额从不用浮点）。 */
export type ModelPriceCard = Schemas["ModelPriceCard"];

/** 已识别的模型能力标签（vision / tools / reasoning 的子集）。 */
export type ModelCapability = "vision" | "tools" | "reasoning";

/**
 * 模型选择键：唯一键为 `(id, origin, providerId)`——同一模型 id 可在多个 BYOK 服务商下
 * 重复出现（且平台再出现一次），故 byok 选择须带 `providerId` 消歧；平台 / 旧存储无。
 */
export type ModelOrigin = ModelCatalogItem["origin"];
export type ModelSelection = {
  id: string;
  origin: ModelOrigin;
  /** byok 行所属服务商 id（平台行为空）。旧存储可能缺省——匹配时回落到 (id, origin)。 */
  providerId?: string | null;
};

/** Stable key for maps / MRU lists —— `(origin, providerId, id)` 三元组。 */
export function modelItemKey(
  item: Pick<ModelCatalogItem, "id" | "origin"> & {
    provider_id?: string | null;
    providerId?: string | null;
  },
): string {
  const providerId = item.provider_id ?? item.providerId ?? "";
  return `${item.origin}:${providerId}:${item.id}`;
}

/**
 * Resolve one catalog row by `(id, origin, provider_id)`。带 providerId 的 byok 选择精确匹配；
 * 无 providerId（平台 / 旧存储）时按 `(id, origin)` 匹配，优先可用行。
 */
export function findCatalogItem(
  models: ModelCatalogItem[],
  sel: ModelSelection,
): ModelCatalogItem | undefined {
  if (sel.origin === "byok" && sel.providerId) {
    const exact = models.find(
      (m) =>
        m.id === sel.id &&
        m.origin === "byok" &&
        m.provider_id === sel.providerId,
    );
    if (exact) return exact;
  }
  const matches = models.filter(
    (m) => m.id === sel.id && m.origin === sel.origin,
  );
  return matches.find((m) => m.available) ?? matches[0];
}

function parseStoredSelection(raw: unknown): ModelSelection | null {
  if (!raw || typeof raw !== "object") return null;
  const o = raw as Record<string, unknown>;
  if (typeof o.id !== "string") return null;
  if (o.origin !== "byok" && o.origin !== "platform") return null;
  const id = o.id.trim();
  if (!id) return null;
  const providerId =
    typeof o.providerId === "string" && o.providerId.trim()
      ? o.providerId.trim()
      : null;
  return { id, origin: o.origin, providerId };
}

/** List the models this user may pick + the account's currently-resolved model. */
export function getModels(): Promise<ModelCatalog> {
  return api.get<ModelCatalog>("/v1/users/me/models");
}

// —— 跨会话的「上次选择」偏好（走统一 UI 持久化层，禁止直碰 localStorage）——

/** 上次在聊天里选择的 (id, origin)（新会话首次的默认建议来源）。 */
const LAST_USED_LEAF = "chat:model:last";

/** The (id, origin) last picked in chat (seeds a new conversation's default suggestion). */
export function getLastUsedModel(): ModelSelection | null {
  return parseStoredSelection(uiGet(LAST_USED_LEAF));
}

/** Remember the last picked (id, origin, providerId) (cross-conversation, global scope). */
export function setLastUsedModel(sel: ModelSelection): void {
  const id = sel.id.trim();
  if (!id) return;
  uiSet(LAST_USED_LEAF, {
    id,
    origin: sel.origin,
    providerId: sel.providerId ?? null,
  });
}
