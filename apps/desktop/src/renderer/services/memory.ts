import { api } from "@/services/api";
import type { MemoryUpdateItem } from "@/stores/conversation";
import type { components } from "@/types/api.generated";

type MemoryUpdateItemView = components["schemas"]["MemoryUpdateItemView"];

/**
 * Long-term AI memory REST client (`/v1/users/me/memory`).
 *
 * The user's memory is the markdown body of their `ai_maintained` rule file
 * (Agent记忆与知识系统). It is edited through the same source-agnostic markdown editor
 * the file workbench uses (see `services/sources/memorySource`), so the contract
 * mirrors the workspace edit contract: full text + a content-addressed `version`
 * baseline the next write does its CAS against.
 */

export interface MemoryDoc {
  content: string;
  /** Content-addressed CAS tag; sent back as the write baseline (stale → conflict). */
  version: string;
  enabled: boolean;
}

export interface MemoryWriteResult {
  ok: boolean;
  version: string;
  conflict: boolean;
}

/** Load the memory document (whole-doc body + version; content APIs for callers). */
export function getMemory(): Promise<MemoryDoc> {
  return api.get<MemoryDoc>("/v1/users/me/memory");
}

/**
 * Write the memory body back (full-document edit). `baseline` is the version the
 * edit was based on; `null` writes unconditionally (清空 / 仍然覆盖). A baseline that
 * no longer matches returns `{ ok: false, conflict: true }` with the live version.
 */
export function writeMemory(
  content: string,
  baseline: string | null,
): Promise<MemoryWriteResult> {
  return api.put<MemoryWriteResult>("/v1/users/me/memory", {
    content,
    baseline,
  });
}

/**
 * A single memory *leaf* (Agent记忆与知识系统 §1.4). The always-injected core is split into
 * 偏好 (`preferences`, GLOBAL-only) + 画像 (`profile`, global or per-project), each its own
 * editable file. `profile` takes an optional `folderId` to address a project's layer.
 */
export type MemoryKind = "preferences" | "profile";

export interface MemoryFileDoc {
  content: string;
  /** Per-file content hash; sent back as the write baseline (stale → conflict). */
  version: string;
}

const memoryFilePath = (kind: MemoryKind, folderId: string | null): string =>
  folderId
    ? `/v1/users/me/memory/files/${kind}?folder_id=${encodeURIComponent(folderId)}`
    : `/v1/users/me/memory/files/${kind}`;

/** Load one memory leaf — 偏好/画像 (global) or a project's 画像 (with `folderId`). */
export function getMemoryFile(
  kind: MemoryKind,
  folderId: string | null = null,
): Promise<MemoryFileDoc> {
  return api.get<MemoryFileDoc>(memoryFilePath(kind, folderId));
}

/**
 * Write one memory leaf back (full-text, CAS-guarded). Empty `content` clears (drops) the
 * leaf. A `baseline` that no longer matches returns `{ ok: false, conflict: true }`.
 */
export function writeMemoryFile(
  kind: MemoryKind,
  content: string,
  baseline: string | null,
  folderId: string | null = null,
): Promise<MemoryWriteResult> {
  return api.put<MemoryWriteResult>(memoryFilePath(kind, folderId), {
    content,
    baseline,
  });
}

/**
 * One offline-consolidation pass in the cross-conversation「记忆动态」feed (记忆编辑器
 * 「最近更新」视图). Same applied-change items the in-conversation card shows, plus the
 * `conversationId` it came from so the feed can link back to that thread.
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
  items?: MemoryUpdateItemView[];
}

/**
 * The signed-in user's recent memory updates across ALL conversations, newest-first
 * (记忆更新对话内可见 §1.6 — the write side's cross-conversation home). Powers the「AI 记忆」
 * editor's「最近更新」view; `limit` caps how many recent passes to pull.
 */
export function listMemoryUpdates(
  limit = 50,
): Promise<MemoryUpdateFeedEntry[]> {
  return api
    .get<{
      updates: MemoryUpdateFeedItemWire[];
    }>(`/v1/users/me/memory/updates?limit=${limit}`)
    .then((r) =>
      r.updates.map((u) => ({
        id: u.id,
        conversationId: u.conversation_id,
        createdAt: u.created_at,
        kind: u.kind === "episodic" ? "episodic" : "semantic",
        summary: u.summary ?? null,
        items: (u.items ?? []).map(
          (it): MemoryUpdateItem => ({
            action: it.action,
            file: it.file,
            section: it.section,
            scope: it.scope,
            content: it.content,
            target: it.target,
            projectId: it.project_id ?? null,
          }),
        ),
      })),
    );
}

/** folder_ids that have project-scoped memory — retained for API callers / diagnostics;
 * the file rail no longer aggregates them under a top-level「项目记忆」folder (each
 * project mounts its own「记忆」child instead). */
export function listMemoryProjects(): Promise<string[]> {
  return api
    .get<{ folders: string[] }>("/v1/users/me/memory/projects")
    .then((r) => r.folders);
}

/**
 * On-demand TOPIC notes (``主题/<slug>.md``) live alongside the always-injected core: the
 * agent pulls them via `consult_memory`, and the「文件」rail's 主题/ folder browses them.
 * `folderId` null = the GLOBAL 主题/ folder, else that project's (same scope convention as
 * the per-leaf surface). Names only ride the listing; a note's body is pulled per-open.
 */
export function listMemoryTopics(
  folderId: string | null = null,
): Promise<string[]> {
  const q = folderId ? `?folder_id=${encodeURIComponent(folderId)}` : "";
  return api
    .get<{ topics: string[] }>(`/v1/users/me/memory/topics${q}`)
    .then((r) => r.topics);
}

const memoryTopicApiPath = (slug: string, folderId: string | null): string => {
  const base = `/v1/users/me/memory/topics/${encodeURIComponent(slug)}`;
  return folderId ? `${base}?folder_id=${encodeURIComponent(folderId)}` : base;
};

/** Load one TOPIC note's body (+ CAS version), in the global or a project's 主题/ folder. */
export function getMemoryTopic(
  slug: string,
  folderId: string | null = null,
): Promise<MemoryFileDoc> {
  return api.get<MemoryFileDoc>(memoryTopicApiPath(slug, folderId));
}

/**
 * Write one TOPIC note back (full-text, CAS-guarded). Empty `content` clears (drops) the
 * note. A `baseline` that no longer matches returns `{ ok: false, conflict: true }`.
 */
export function writeMemoryTopic(
  slug: string,
  content: string,
  baseline: string | null,
  folderId: string | null = null,
): Promise<MemoryWriteResult> {
  return api.put<MemoryWriteResult>(memoryTopicApiPath(slug, folderId), {
    content,
    baseline,
  });
}

/** Direction for {@link moveMemoryBullet} (位置即作用域纠错). */
export type MemoryMoveDirection = "to_project" | "to_global";

export type MemoryMoveKind = "preferences" | "profile" | "topic";

export interface MemoryMoveBulletInput {
  content: string;
  section: string;
  folderId: string;
  direction: MemoryMoveDirection;
  kind?: MemoryMoveKind;
  topicSlug?: string | null;
  sourceBaseline?: string | null;
  targetBaseline?: string | null;
}

export interface MemoryMoveBulletResult {
  ok: boolean;
  conflict: boolean;
  sourceVersion: string;
  targetVersion: string;
  message?: string | null;
}

/**
 * Move one bullet between GLOBAL and the current project layer (remove + add under
 * the same section). Illegal sections (偏好 / 纠正记录 → project, 项目约束 → global)
 * return HTTP 422 with a clear message.
 */
export function moveMemoryBullet(
  input: MemoryMoveBulletInput,
): Promise<MemoryMoveBulletResult> {
  return api
    .post<{
      ok: boolean;
      conflict: boolean;
      source_version: string;
      target_version: string;
      message?: string | null;
    }>("/v1/users/me/memory/move-bullet", {
      content: input.content,
      section: input.section,
      folder_id: input.folderId,
      direction: input.direction,
      kind: input.kind ?? "profile",
      topic_slug: input.topicSlug ?? null,
      source_baseline: input.sourceBaseline ?? null,
      target_baseline: input.targetBaseline ?? null,
    })
    .then((r) => ({
      ok: r.ok,
      conflict: r.conflict,
      sourceVersion: r.source_version,
      targetVersion: r.target_version,
      message: r.message ?? null,
    }));
}
