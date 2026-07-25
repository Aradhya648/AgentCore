// 模型组合（llm-model-profiles）REST + shared cache for the mobile client.
//
// Chat picks a combination (or follows the account default); 设置·模型配置 manages CRUD
// + default. Slot models still come from GET /v1/users/me/models.
import { apiFetch } from "@/api/client";
import type { ModelCatalog } from "@/api/models";
import type { components } from "@/types/api.generated";
import { useEffect, useState } from "react";

type Schemas = components["schemas"];

export type ModelProfileSlot = Schemas["ModelProfileSlot"];
export type LlmModelProfileView = Schemas["LlmModelProfileView"];
export type LlmModelProfileListResponse =
  Schemas["LlmModelProfileListResponse"];
export type CreateLlmModelProfileRequest =
  Schemas["CreateLlmModelProfileRequest"];
export type UpdateLlmModelProfileRequest =
  Schemas["UpdateLlmModelProfileRequest"];

async function errorMessage(res: Response, fallback: string): Promise<string> {
  try {
    const body = (await res.json()) as { error?: { message?: string } };
    return body.error?.message ?? `${fallback} (${res.status})`;
  } catch {
    return `${fallback} (${res.status})`;
  }
}

export async function listModelProfiles(): Promise<LlmModelProfileListResponse> {
  const res = await apiFetch("/v1/users/me/llm-model-profiles");
  if (!res.ok) throw new Error(await errorMessage(res, "加载模型组合失败"));
  return (await res.json()) as LlmModelProfileListResponse;
}

export async function createModelProfile(
  input: CreateLlmModelProfileRequest,
): Promise<LlmModelProfileView> {
  const res = await apiFetch("/v1/users/me/llm-model-profiles", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new Error(await errorMessage(res, "创建失败"));
  return (await res.json()) as LlmModelProfileView;
}

export async function updateModelProfile(
  id: string,
  input: UpdateLlmModelProfileRequest,
): Promise<LlmModelProfileView> {
  const res = await apiFetch(`/v1/users/me/llm-model-profiles/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!res.ok) throw new Error(await errorMessage(res, "保存失败"));
  return (await res.json()) as LlmModelProfileView;
}

export async function deleteModelProfile(id: string): Promise<void> {
  const res = await apiFetch(`/v1/users/me/llm-model-profiles/${id}`, {
    method: "DELETE",
  });
  if (!res.ok) throw new Error(await errorMessage(res, "删除失败"));
}

export async function setDefaultModelProfile(
  profileId: string,
): Promise<LlmModelProfileView> {
  const res = await apiFetch("/v1/users/me/llm-model-profiles/default", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ profile_id: profileId }),
  });
  if (!res.ok) throw new Error(await errorMessage(res, "设置默认失败"));
  return (await res.json()) as LlmModelProfileView;
}

/** Resolve a slot to a catalog display name (or raw model id). */
export function slotDisplayName(
  catalog: ModelCatalog | null,
  slot: ModelProfileSlot | null | undefined,
): string | null {
  if (!slot?.model?.trim()) return null;
  const model = slot.model.trim();
  const models = catalog?.models ?? [];
  const hit =
    models.find(
      (m) =>
        m.id === model &&
        m.origin === slot.origin &&
        (m.provider_id ?? null) === (slot.provider_id ?? null),
    ) ??
    models.find((m) => m.id === model && m.origin === slot.origin) ??
    models.find((m) => m.id === model);
  return hit?.display_name ?? model;
}

/** One-line summary: 主 · Worker（空=跟随主模型）. */
export function profileSlotsSummary(
  catalog: ModelCatalog | null,
  profile: LlmModelProfileView,
): string {
  const main = slotDisplayName(catalog, profile.main) ?? profile.main.model;
  const worker = profile.worker
    ? (slotDisplayName(catalog, profile.worker) ?? profile.worker.model)
    : "跟随主模型";
  return `${main} · ${worker}`;
}

export function findProfile(
  list: LlmModelProfileListResponse | null,
  profileId: string | null | undefined,
): LlmModelProfileView | null {
  if (!list || !profileId) return null;
  return list.data.find((p) => p.id === profileId) ?? null;
}

export function defaultProfile(
  list: LlmModelProfileListResponse | null,
): LlmModelProfileView | null {
  if (!list) return null;
  const id = list.default_model_profile_id;
  if (id) {
    const hit = list.data.find((p) => p.id === id);
    if (hit) return hit;
  }
  return list.data.find((p) => p.is_default) ?? list.data[0] ?? null;
}

/** Badge label: conversation override name, else account default name. */
export function profileDisplayLabel(
  list: LlmModelProfileListResponse | null,
  conversationProfileId: string | null | undefined,
): string | null {
  const override = findProfile(list, conversationProfileId);
  if (override) return override.name;
  return defaultProfile(list)?.name ?? null;
}

// --- last-used profile (新对话继承上次选择) ---------------------------------------------
const LAST_PROFILE_KEY = "agentcore.mobile.lastModelProfile";

export function getLastModelProfileId(): string | null {
  try {
    const raw = localStorage.getItem(LAST_PROFILE_KEY)?.trim();
    return raw || null;
  } catch {
    return null;
  }
}

export function setLastModelProfileId(id: string): void {
  try {
    localStorage.setItem(LAST_PROFILE_KEY, id);
  } catch {
    /* best-effort */
  }
}

export function clearLastModelProfileId(): void {
  try {
    localStorage.removeItem(LAST_PROFILE_KEY);
  } catch {
    /* best-effort */
  }
}

// --- shared cache ----------------------------------------------------------------------
let cache: LlmModelProfileListResponse | null = null;
let inflight: Promise<LlmModelProfileListResponse> | null = null;
const subscribers = new Set<(c: LlmModelProfileListResponse) => void>();

async function load(force: boolean): Promise<void> {
  if (!force && cache) return;
  if (!inflight) inflight = listModelProfiles();
  try {
    const next = await inflight;
    cache = next;
    for (const fn of subscribers) fn(next);
  } finally {
    inflight = null;
  }
}

/** Drop cache after settings mutations so chat reopens fresh. */
export function invalidateModelProfilesCache(): void {
  cache = null;
}

export interface UseModelProfilesResult {
  data: LlmModelProfileListResponse | null;
  loading: boolean;
  error: string | null;
  refetch: () => void;
}

export function useModelProfiles(opts?: {
  force?: boolean;
}): UseModelProfilesResult {
  const force = opts?.force ?? false;
  const [data, setData] = useState<LlmModelProfileListResponse | null>(cache);
  const [loading, setLoading] = useState(!cache);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let alive = true;
    const sub = (c: LlmModelProfileListResponse) => {
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
            setError(e instanceof Error ? e.message : "加载模型组合失败");
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
      /* next mount surfaces via shared error path */
    });
  };

  return { data, loading, error, refetch };
}
