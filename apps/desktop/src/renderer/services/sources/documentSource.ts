import type { FileNode, FilePreviewResult, FileSource } from "@/lib/fileSource";
import { getDocument, writeDocument } from "@/services/documents";

/**
 * A {@link FileSource} over the user's rule **documents**, so the「你的规则」rail can reuse the
 * same markdown editor host ({@link MarkdownFileEditor}) the file workbench and「AI 记忆」use —
 * full-text edit + preview + AI 改写 + CAS conflict handling, all for free (Agent记忆与知识系统
 * §1.6 形态基准, §5.7 前端规则入口).
 *
 * Unlike the workspace/memory surfaces, `/v1/documents` addresses nodes by **id**, so a rule
 * doc's synthetic tab PATH simply IS its document id. The source is path-aware (the editor
 * passes each tab's path — the doc id — to every call), so ONE instance serves every rule doc
 * of every scope. tree / CRUD are never reached (the rail lists + creates + deletes rules
 * directly via `services/documents`; the editor only calls `readForEdit` / `writeText`), so
 * they reject rather than pretend. `version.etag` carries the content hash — the editor sends
 * it back as the write baseline, so a concurrent edit (another device / a drafted-by-AI
 * change) surfaces as a conflict, never a silent clobber.
 */

const unsupported = (): Promise<never> =>
  Promise.reject(new Error("规则文档不支持该操作"));

export function createDocumentSource(): FileSource {
  return {
    id: "documents",
    label: "规则",
    caps: { watch: false, transfer: false, edit: true, snapshots: false },
    listDir: (): Promise<FileNode[]> => Promise.resolve([]),
    read: async (path): Promise<FilePreviewResult> => {
      const doc = await getDocument(path);
      return { kind: "text", text: doc.content, truncated: false };
    },
    createFile: unsupported,
    mkdir: unsupported,
    move: unsupported,
    delete: unsupported,
    readForEdit: async (path) => {
      const doc = await getDocument(path);
      return {
        text: doc.content,
        version: { etag: doc.version },
        encoding: "utf-8",
        eol: "lf",
      };
    },
    writeText: async (path, input) => {
      const r = await writeDocument(
        path,
        input.content,
        input.baseline?.etag ?? null,
      );
      return r.ok
        ? { ok: true as const, version: { etag: r.version } }
        : {
            ok: false as const,
            reason: "conflict" as const,
            version: { etag: r.version },
          };
    },
  };
}
