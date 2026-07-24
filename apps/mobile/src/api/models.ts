// Model catalog (模型目录 · 会话级模型切换) REST + a tiny shared cache for the mobile client.
//
// Mirrors the desktop capability: `GET /v1/users/me/models` lists the models this user may
// pick (greyed when they need a BYOK key they lack) plus the account's currently-resolved
// model. The compose UI (ModelPicker + 当前模型 badge) reads this; picking one PATCHes
// `conversations.model` + `model_origin` (+ `model_provider_id` for BYOK) — see
// setConversationModel in api/conversations.ts.
//
// Mobile has no react-query (unlike desktop), so — following the plain-fetch llm-key pattern
// (api/model.ts) — this exposes a plain `getModels()` fetch plus a small `useModels()` hook
// backed by a module-level cache + pub/sub so the always-mounted badge and the on-demand
// picker share a single request rather than each hitting the network.
import { apiFetch } from "@/api/client";
import type { components } from "@/types/api.generated";
import { useEffect, useState } from "react";

type Schemas = components["schemas"];
type RawCatalog = Schemas["ModelCatalogResponse"];

// 多服务商契约升级：同一模型 id 可在多个 BYOK 服务商下重复出现，唯一键升级为
// (id, origin, provider_id)。contract-rest-types 由桌面块重生成——这里用交集在端内补齐
// provider_id / provider_label（附加可选字段，重生成前后都成立），保持本端类型自洽。
/** The account's currently-resolved model (+ which BYOK provider it runs on). */
export type ModelCatalogCurrent = RawCatalog["current"] & {
  provider_id?: string | null;
};
/** One selectable (or greyed-out) model row, keyed by (id, origin, provider_id). */
export type ModelCatalogItem = RawCatalog["models"][number] & {
  provider_id?: string | null;
  provider_label?: string | null;
};
/** The user's selectable model catalog + the account's currently-resolved model. */
export type ModelCatalog = Omit<RawCatalog, "current" | "models"> & {
  current: ModelCatalogCurrent;
  models: ModelCatalogItem[];
};
/** Credential origin when a model is selected. */
export type ModelOrigin = ModelCatalogItem["origin"];
/** Session-level model selection key. For BYOK, `providerId` disambiguates the same model
 *  id across providers (required by PATCH /conversations); platform picks omit it. */
export type ModelPick = {
  id: string;
  origin: ModelOrigin;
  providerId?: string | null;
};

/** Fetch the user's model catalog (owner-scoped "me"). */
export async function getModels(): Promise<ModelCatalog> {
  const res = await apiFetch("/v1/users/me/models");
  if (!res.ok) throw new Error(`加载模型目录失败 (${res.status})`);
  return (await res.json()) as ModelCatalog;
}

export function modelPickKey(pick: ModelPick): string {
  return `${pick.id}:${pick.origin}:${pick.providerId ?? ""}`;
}

export function picksEqual(
  a: ModelPick | null | undefined,
  b: ModelPick | null | undefined,
): boolean {
  if (!a || !b) return a === b;
  return (
    a.id === b.id &&
    a.origin === b.origin &&
    (a.providerId ?? null) === (b.providerId ?? null)
  );
}

/** Build a pick for a BYOK model — only tags `providerId` when one is known. */
function byokPick(
  id: string,
  providerId: string | null | undefined,
): ModelPick {
  const pid = providerId?.trim();
  return pid ? { id, origin: "byok", providerId: pid } : { id, origin: "byok" };
}

export function catalogCurrentPick(
  catalog: ModelCatalog | null,
): ModelPick | null {
  const cur = catalog?.current;
  if (!cur?.id?.trim()) return null;
  const id = cur.id.trim();
  return cur.origin === "byok"
    ? byokPick(id, cur.provider_id)
    : { id, origin: cur.origin };
}

export function conversationModelPick(
  model: string | null | undefined,
  origin: ModelOrigin | null | undefined,
  providerId?: string | null,
): ModelPick | null {
  const id = model?.trim();
  if (!id) return null;
  const resolved = origin ?? "byok";
  return resolved === "byok"
    ? byokPick(id, providerId)
    : { id, origin: resolved };
}

function findCatalogItem(
  catalog: ModelCatalog | null,
  pick: ModelPick,
): ModelCatalogItem | undefined {
  const models = catalog?.models;
  if (!models) return undefined;
  return (
    // Exact (id, origin, provider_id) — the unique key.
    models.find(
      (m) =>
        m.id === pick.id &&
        m.origin === pick.origin &&
        (m.provider_id ?? null) === (pick.providerId ?? null),
    ) ??
    // Fall back to (id, origin), then id — tolerant of stale/ambiguous picks.
    models.find((m) => m.id === pick.id && m.origin === pick.origin) ??
    models.find((m) => m.id === pick.id)
  );
}

// --- last-used (新对话继承上次选择) -----------------------------------------------------
// A frontend-only memory of the last concrete (id, origin) pick. A draft (no conversation
// yet) can't be PATCHed, so we remember the choice here and apply it to the freshly-created
// conversation on first send. Clearing (跟随账号默认) forgets it. Legacy plain-id records
// are discarded on read.
const LAST_MODEL_KEY = "agentcore.mobile.lastModel";

function parseLastModel(raw: string): ModelPick | null {
  try {
    const parsed = JSON.parse(raw) as {
      id?: string;
      origin?: string;
      providerId?: string | null;
    };
    const id = parsed.id?.trim();
    if (!id) return null;
    if (parsed.origin === "byok") {
      return byokPick(id, parsed.providerId);
    }
    if (parsed.origin === "platform") {
      return { id, origin: "platform" };
    }
  } catch {
    /* legacy plain id or corrupt value — discard */
  }
  return null;
}

export function getLastModel(): ModelPick | null {
  try {
    const raw = localStorage.getItem(LAST_MODEL_KEY);
    if (!raw) return null;
    return parseLastModel(raw);
  } catch {
    return null;
  }
}

export function setLastModel(pick: ModelPick): void {
  try {
    localStorage.setItem(LAST_MODEL_KEY, JSON.stringify(pick));
  } catch {
    /* best-effort: a private-mode / quota failure just skips inheritance */
  }
}

export function clearLastModel(): void {
  try {
    localStorage.removeItem(LAST_MODEL_KEY);
  } catch {
    /* best-effort */
  }
}

// --- shared cache (no react-query) ------------------------------------------------------
let cache: ModelCatalog | null = null;
let inflight: Promise<ModelCatalog> | null = null;
const subscribers = new Set<(c: ModelCatalog) => void>();

/** Load the catalog into the shared cache; dedupes concurrent callers and fans the result
 *  out to every mounted consumer. `force` revalidates even when a cached value exists. */
async function load(force: boolean): Promise<void> {
  if (!force && cache) return;
  if (!inflight) inflight = getModels();
  try {
    const next = await inflight;
    cache = next;
    for (const fn of subscribers) fn(next);
  } finally {
    inflight = null;
  }
}

export interface UseModelsResult {
  data: ModelCatalog | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

/**
 * Subscribe to the shared model catalog. The always-mounted badge calls this cache-first
 * (cheap: one fetch per session); the picker passes `{ force: true }` so opening it
 * revalidates availability (e.g. after the user just added a BYOK key), updating the badge
 * too via the shared cache.
 */
export function useModels(opts?: { force?: boolean }): UseModelsResult {
  const force = opts?.force ?? false;
  const [data, setData] = useState<ModelCatalog | null>(cache);
  const [loading, setLoading] = useState(!cache);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const sub = (c: ModelCatalog) => {
      if (alive) setData(c);
    };
    subscribers.add(sub);
    if (cache) setData(cache);
    if (!force && cache) {
      setLoading(false);
    } else {
      setLoading(true);
      setError(null);
      load(force)
        .catch((e) => {
          if (alive) {
            setError(e instanceof Error ? e.message : "加载模型目录失败");
          }
        })
        .finally(() => {
          if (alive) setLoading(false);
        });
    }
    return () => {
      alive = false;
      subscribers.delete(sub);
    };
  }, [force]);

  const refetch = () => {
    void load(true).catch(() => {
      /* surfaced on the next mounted render via the shared error path */
    });
  };

  return { data, loading, error, refetch };
}

/**
 * The human label for the model a conversation runs on: the conversation's explicit override
 * when set, else the account's resolved model (`catalog.current`). Maps a (id, origin) pick
 * → catalog `display_name`, falling back to the raw id (and null when nothing is known yet).
 */
export function modelDisplayLabel(
  catalog: ModelCatalog | null,
  overrideModel: ModelPick | null | undefined,
): string | null {
  const pick = overrideModel ?? catalogCurrentPick(catalog);
  if (!pick) return null;
  return findCatalogItem(catalog, pick)?.display_name ?? pick.id;
}
