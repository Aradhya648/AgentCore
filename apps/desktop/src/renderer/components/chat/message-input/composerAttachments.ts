import type { EntryKind } from "@/lib/fileIndex";
import type { FileSource } from "@/lib/fileSource";
import { createLocalRootSource } from "@/services/sources/localRootSource";
import { createCloudWorkspaceSource } from "@/services/sources/workspaceSource";
import { getWorkspaceBinding } from "@/services/workspaceBinding";

/** 已选附件（含正文，仅发送时携带；气泡只展示元信息）。 */
export interface PendingAttachment {
  id: string;
  /** kind:sourceId:relPath，用于去重。 */
  key: string;
  name: string;
  /** 展示路径：优先工作区相对 ``attachments/…``，绝不含 OS 绝对路径。 */
  path: string;
  text: string;
  truncated: boolean;
  kind: EntryKind;
  /** 仅 kind=conversation：被引用对话的 id。 */
  conversationId?: string;
  /** 引用即驻留：已写入对话工作区时的相对路径。 */
  workspacePath?: string;
  /** 主进程暂存 id（草稿 / 待云端上传）；发送前 finalize / consume。 */
  stagingId?: string;
  /** 二进制驻留：无 UTF-8 正文内联。 */
  binary?: boolean;
}

export const TEXT_PREVIEW_CAP = 256 * 1024;

export const CONV_MENTION_MSG_LIMIT = 40;
export const CONV_MENTION_CHAR_CAP = 60 * 1024;

export async function readDroppedFile(
  file: File,
): Promise<
  { ok: true; text: string; truncated: boolean } | { ok: false; reason: string }
> {
  if (file.type.startsWith("image/")) {
    return { ok: false, reason: "暂不支持图片附件（模型尚无视觉能力）" };
  }
  const head = await file.slice(0, TEXT_PREVIEW_CAP + 1).arrayBuffer();
  const bytes = new Uint8Array(head);
  if (bytes.includes(0)) {
    return {
      ok: false,
      reason: "二进制文件请在桌面端附加（将驻留到工作区）",
    };
  }
  const text = new TextDecoder("utf-8").decode(
    bytes.subarray(0, Math.min(bytes.length, TEXT_PREVIEW_CAP)),
  );
  return { ok: true, text, truncated: file.size > TEXT_PREVIEW_CAP };
}

export function formatConversationContext(
  messages: { role: string; content: string }[],
): { text: string; truncated: boolean } {
  const usable = messages.filter((m) => m.content.trim());
  const recent = usable.slice(-CONV_MENTION_MSG_LIMIT);
  let truncated = recent.length < usable.length;
  const body = recent
    .map(
      (m) => `${m.role === "assistant" ? "助手" : "用户"}: ${m.content.trim()}`,
    )
    .join("\n\n");
  let text = body;
  if (text.length > CONV_MENTION_CHAR_CAP) {
    text = text.slice(text.length - CONV_MENTION_CHAR_CAP);
    truncated = true;
  }
  return { text: text.trim(), truncated };
}

export function detectMention(
  text: string,
  caret: number,
): { start: number; query: string } | null {
  let at = -1;
  for (let i = caret - 1; i >= 0; i--) {
    const ch = text[i];
    if (ch === "@") {
      at = i;
      break;
    }
    if (ch === " " || ch === "\n" || ch === "\t") return null;
  }
  if (at === -1) return null;
  const before = at === 0 ? "" : text[at - 1];
  if (before && !/\s/.test(before)) return null;
  return { start: at, query: text.slice(at + 1, caret) };
}

export async function buildMentionSources(
  conversationId: string | null,
): Promise<FileSource[]> {
  const sources: FileSource[] = [];

  if (conversationId) {
    try {
      const binding = await getWorkspaceBinding(conversationId);
      if (binding.mode === "cloud") {
        sources.push(
          createCloudWorkspaceSource(`conv:${conversationId}`, "工作区"),
        );
      }
    } catch {
      // Binding unknown — index local roots only.
    }
  }

  const roots = (await window.fsApi?.listRoots()) ?? [];
  for (const r of roots) sources.push(createLocalRootSource(r.id, r.name));
  return sources;
}
