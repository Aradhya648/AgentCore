// Long-term AI memory REST client for mobile (Agent记忆与知识系统 §一).
//
// Mirrors the desktop `services/memory.ts` contract, but over the bearer-token
// `apiFetch` (mobile has no cookie origin). 精简版 (手机端): GLOBAL scope only — no
// per-project layer, no AI 改写 / preview. The phone is a 查看 + 改 + 删 lens on the
// always-injected core (偏好 全局 + 画像 全局) and the on-demand 主题 notes, plus the
// master switch and cross-conversation「最近更新」feed. The contract mirrors the
// workspace edit contract: full text + a content-addressed `version` baseline the
// next write does its CAS against.
import { apiFetch } from "@/api/client";
import type { MemoryUpdateItem } from "@/api/conversations";

export interface MemoryDoc {
  content: string;
  /** Content-addressed CAS tag; sent back as the write baseline (stale → conflict). */
  version: string;
  enabled: boolean;
}

export interface MemoryFileDoc {
  content: string;
  /** Per-file content hash; sent back as the write baseline (stale → conflict). */
  version: string;
}

export interface MemoryWriteResult {
  ok: boolean;
  version: string;
  conflict: boolean;
}

/**
 * A single always-injected memory leaf: 偏好 (preferences, global-only) and 画像
 * (profile). The mobile lite surface edits the GLOBAL layer of each.
 */
export type MemoryKind = "preferences" | "profile";

/**
 * A failed memory REST call, carrying the HTTP status so callers can tell a missing
 * endpoint (404/501 — this deployed backend predates the feature) apart from a
 * transient failure. Still a plain Error subclass, so existing catch sites that only
 * read `.message` are unaffected.
 */
export class MemoryApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
    this.name = "MemoryApiError";
  }
}

/**
 * Whether an error means the deployed backend lacks this endpoint (404/501) — the
 * 前后端版本漂移 window (a newer client calling an endpoint an older *deployed* backend
 * lacks, e.g. 记忆·主题 shipped in the client before the backend redeploy). Retrying
 * can't fix it, so the caller degrades to a calm "暂不可用" note (no red error).
 */
export function isFeatureUnavailable(err: unknown): boolean {
  return (
    err instanceof MemoryApiError && (err.status === 404 || err.status === 501)
  );
}

async function getJson<T>(path: string, fallback: string): Promise<T> {
  const res = await apiFetch(path);
  if (!res.ok)
    throw new MemoryApiError(res.status, `${fallback} (${res.status})`);
  return (await res.json()) as T;
}

async function putJson<T>(
  path: string,
  body: unknown,
  fallback: string,
): Promise<T> {
  const res = await apiFetch(path, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!res.ok)
    throw new MemoryApiError(res.status, `${fallback} (${res.status})`);
  return (await res.json()) as T;
}

/** Load the master switch (the whole-doc body/version ride along, unused by the lite UI). */
export function getMemory(): Promise<MemoryDoc> {
  return getJson<MemoryDoc>("/v1/users/me/memory", "加载记忆失败");
}

/** Flip the long-term memory master switch (off = stop injecting AND growing). */
export function setMemoryEnabled(enabled: boolean): Promise<MemoryDoc> {
  return putJson<MemoryDoc>(
    "/v1/users/me/memory/enabled",
    { enabled },
    "设置失败",
  );
}

/** Load one always-injected core leaf (偏好 / 画像), GLOBAL layer. */
export function getMemoryFile(kind: MemoryKind): Promise<MemoryFileDoc> {
  return getJson<MemoryFileDoc>(
    `/v1/users/me/memory/files/${kind}`,
    "加载失败",
  );
}

/**
 * Write one core leaf back (full-text, CAS-guarded). Empty `content` clears the leaf.
 * A `baseline` that no longer matches returns `{ ok: false, conflict: true }`.
 */
export function writeMemoryFile(
  kind: MemoryKind,
  content: string,
  baseline: string | null,
): Promise<MemoryWriteResult> {
  return putJson<MemoryWriteResult>(
    `/v1/users/me/memory/files/${kind}`,
    { content, baseline },
    "保存失败",
  );
}

/** GLOBAL 主题 note slugs (on-demand notes the agent pulls via consult_memory). */
export function listMemoryTopics(): Promise<string[]> {
  return getJson<{ topics: string[] }>(
    "/v1/users/me/memory/topics",
    "加载主题失败",
  ).then((r) => r.topics);
}

/** Load one GLOBAL 主题 note's body (+ CAS version). */
export function getMemoryTopic(slug: string): Promise<MemoryFileDoc> {
  return getJson<MemoryFileDoc>(
    `/v1/users/me/memory/topics/${encodeURIComponent(slug)}`,
    "加载主题失败",
  );
}

/**
 * Write one 主题 note back (full-text, CAS-guarded). Empty `content` deletes the note.
 * A `baseline` that no longer matches returns `{ ok: false, conflict: true }`.
 */
export function writeMemoryTopic(
  slug: string,
  content: string,
  baseline: string | null,
): Promise<MemoryWriteResult> {
  return putJson<MemoryWriteResult>(
    `/v1/users/me/memory/topics/${encodeURIComponent(slug)}`,
    { content, baseline },
    "保存失败",
  );
}

/**
 * One offline-consolidation pass in the cross-conversation「最近更新」feed (§1.6).
 * Same applied-change items as the in-conversation card, plus `conversationId` so the
 * feed can jump back to the source thread.
 */
export interface MemoryUpdateFeedEntry {
  id: string;
  conversationId: string;
  createdAt: string;
  kind: "episodic" | "semantic";
  summary?: string | null;
  items: MemoryUpdateItem[];
}

interface MemoryUpdateFeedItemWire {
  id: string;
  conversation_id: string;
  created_at: string;
  kind?: string;
  summary?: string | null;
  items?: Array<{
    action: string;
    file: string;
    section: string;
    scope: string;
    content: string;
    target: string;
  }>;
}

/**
 * The signed-in user's recent memory updates across ALL conversations, newest-first
 * (记忆更新对话内可见 §1.6 — write-side home on `/memory`). `limit` caps how many
 * recent passes to pull.
 */
export async function listMemoryUpdates(
  limit = 30,
): Promise<MemoryUpdateFeedEntry[]> {
  const data = await getJson<{ updates: MemoryUpdateFeedItemWire[] }>(
    `/v1/users/me/memory/updates?limit=${limit}`,
    "加载记忆更新失败",
  );
  return (data.updates ?? []).map((u) => ({
    id: u.id,
    conversationId: u.conversation_id,
    createdAt: u.created_at,
    kind: u.kind === "episodic" ? "episodic" : "semantic",
    summary: u.summary ?? null,
    items: (u.items ?? []).map((it) => ({
      action: it.action,
      file: it.file,
      section: it.section ?? "",
      scope: it.scope ?? "global",
      content: it.content ?? "",
      target: it.target ?? "",
    })),
  }));
}
