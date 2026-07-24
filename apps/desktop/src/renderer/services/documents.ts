import { api } from "@/services/api";

/**
 * Document tree REST client (`/v1/documents`) — the「一切皆文档」carrier (Agent记忆与知识系统
 * §5.7 载体). This phase's load-bearing use is **user rules**: a user rule is just a
 * `role='rule', ai_maintained=false` document (§5.2), created / edited / deleted here and
 * injected ahead of AI memory with authoritative「必须」wording (§二 两档措辞).
 *
 * Nodes are addressed by **id** (not a source-relative path like the workspace/memory
 * surfaces), so the editor host reaches a rule doc through {@link createDocumentSource},
 * whose synthetic path IS the document id. CAS mirrors the memory editor — a content write
 * carries the content-hash `version` baseline and reports a conflict instead of clobbering.
 *
 * Scope is the `folderId` column (§5.7 过渡态：项目作用域由 `documents.folder_id` 桥接，
 * 待 Folder 并入文档树后折叠为「位置即作用域」终态): `null` = the GLOBAL layer (all
 * conversations), else that project's layer (only that folder's conversations).
 */

/** A tree node's metadata (list rows — body omitted so a listing stays light). */
export interface DocumentNode {
  id: string;
  parentId: string | null;
  /** Scope: null = GLOBAL layer, else the project (folder) this rule is bound to. */
  folderId: string | null;
  kind: "folder" | "document";
  role: "rule" | "general";
  /** true = AI-maintained memory (not user-settable here); false = a user-owned doc. */
  aiMaintained: boolean;
  applyMode: string;
  name: string;
}

/** A node plus its markdown body + content-hash CAS tag (the editor's load payload). */
export interface DocumentDetail extends DocumentNode {
  content: string;
  version: string;
}

export interface DocumentWriteResult {
  ok: boolean;
  /** Content-addressed CAS tag; sent back as the next write's baseline (stale → conflict). */
  version: string;
  conflict: boolean;
}

interface DocumentNodeWire {
  id: string;
  parent_id: string | null;
  folder_id: string | null;
  kind: string;
  role: string;
  ai_maintained: boolean;
  apply_mode: string;
  name: string;
}

interface DocumentDetailWire extends DocumentNodeWire {
  content: string;
  version: string;
}

const toNode = (w: DocumentNodeWire): DocumentNode => ({
  id: w.id,
  parentId: w.parent_id,
  folderId: w.folder_id,
  kind: w.kind === "folder" ? "folder" : "document",
  role: w.role === "rule" ? "rule" : "general",
  aiMaintained: w.ai_maintained,
  applyMode: w.apply_mode,
  name: w.name,
});

const toDetail = (w: DocumentDetailWire): DocumentDetail => ({
  ...toNode(w),
  content: w.content,
  version: w.version,
});

/** List a folder's direct children (`parentId` null = the user's top-level nodes). */
export function listDocuments(
  parentId: string | null = null,
): Promise<DocumentNode[]> {
  const q = parentId ? `?parent_id=${encodeURIComponent(parentId)}` : "";
  return api
    .get<DocumentNodeWire[]>(`/v1/documents${q}`)
    .then((rows) => rows.map(toNode));
}

/**
 * All of the user's own rule documents across scopes (§5.2 user rules =
 * `role='rule', ai_maintained=false`). Phase-1 rules are top-level of their scope
 * (global rules + `remember`'s 用户规则.md + project rules created here all sit at
 * `parent_id=null`), so ONE top-level listing gathers them; partition by `folderId`
 * for the GLOBAL vs per-project layers. AI memory (记忆 folder + its ai_maintained
 * notes) and any general docs are filtered out.
 */
export function listUserRules(): Promise<DocumentNode[]> {
  return listDocuments(null).then((nodes) =>
    nodes.filter(
      (n) => n.role === "rule" && !n.aiMaintained && n.kind === "document",
    ),
  );
}

/** Load one document's body + CAS version (the editor's load). */
export function getDocument(id: string): Promise<DocumentDetail> {
  return api
    .get<DocumentDetailWire>(`/v1/documents/${encodeURIComponent(id)}`)
    .then(toDetail);
}

/**
 * Create a user rule document in a scope (`folderId` null = global, else that project).
 * Always `role='rule', ai_maintained=false, apply_mode='always'` (the API pins authorship).
 */
export function createRuleDocument(
  name: string,
  folderId: string | null = null,
  content = "",
): Promise<DocumentDetail> {
  return api
    .post<DocumentDetailWire>("/v1/documents", {
      name,
      kind: "document",
      role: "rule",
      content,
      parent_id: null,
      folder_id: folderId,
    })
    .then(toDetail);
}

/**
 * Overwrite a document's body (full-text, CAS-guarded). `baseline` is the version the edit
 * was based on; `null` writes unconditionally (仍然覆盖). A stale baseline returns
 * `{ ok: false, conflict: true }` with the live version.
 */
export function writeDocument(
  id: string,
  content: string,
  baseline: string | null,
): Promise<DocumentWriteResult> {
  return api.put<DocumentWriteResult>(
    `/v1/documents/${encodeURIComponent(id)}`,
    { content, baseline },
  );
}

/** Rename a document (content untouched). */
export function renameDocument(
  id: string,
  name: string,
): Promise<DocumentNode> {
  return api
    .patch<DocumentNodeWire>(`/v1/documents/${encodeURIComponent(id)}`, {
      name,
    })
    .then(toNode);
}

/** Soft-delete a document (and, for a folder, its subtree). */
export function deleteDocument(id: string): Promise<DocumentWriteResult> {
  return api.delete<DocumentWriteResult>(
    `/v1/documents/${encodeURIComponent(id)}`,
  );
}
