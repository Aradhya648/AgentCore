// Agent-chat attachments (composer 附件 · Agent 对话).
//
// An agent-chat attachment is NOT an uploaded file reference (that's IM, api/messaging.ts):
// the model has no vision and the workspace isn't the transport here, so the client reads a
// text file's CONTENT and ships it inline in the send body. The backend folds that text into
// the turn's context and durably persists it into the conversation workspace itself.
//
// Mirrors the desktop composer's `readDroppedFile` (chat/MessageInput.tsx) byte-for-byte so
// both clients refuse the same files and truncate at the same 256KB boundary: a picked file
// is the user's explicit grant to read it, images are refused (no vision), NUL-containing
// blobs are treated as binary, and oversize text is capped + flagged `truncated`.

/** Cap a single attachment's shipped text at 256KB — the same threshold the desktop and the
 *  server's `readFile` use, so「拖入 / @ 引用 / 手机端选取」all truncate identically. */
export const TEXT_PREVIEW_CAP = 256 * 1024;

/** The agent-chat send-time attachment payload (mirrors the backend `MessageAttachment` /
 *  desktop `OutgoingAttachment`): the extracted `text` is the context, `path` is just the
 *  display name on mobile (no source tree), `kind` is always `file` (no directory picker). */
export interface MessageAttachment {
  name: string;
  path: string;
  /** The file's text content (UTF-8, capped at {@link TEXT_PREVIEW_CAP}). */
  text: string;
  truncated: boolean;
  kind: "file" | "dir";
}

/** Outcome of reading one picked file: a ready attachment, or a reason it was refused. */
export type ReadAttachmentResult =
  | { ok: true; attachment: MessageAttachment }
  | { ok: false; reason: string };

/**
 * Read a user-picked file into a text attachment, applying the shared policy: images are
 * refused (the model has no vision yet), NUL-containing files are treated as binary, and the
 * text is read UTF-8 and capped at 256KB (`truncated` flags an oversize source). Picking the
 * file is the user's explicit grant to read its bytes.
 */
export async function readTextAttachment(
  file: File,
): Promise<ReadAttachmentResult> {
  if (file.type.startsWith("image/")) {
    return { ok: false, reason: "暂不支持图片附件（模型尚无视觉能力）" };
  }
  const head = await file.slice(0, TEXT_PREVIEW_CAP + 1).arrayBuffer();
  const bytes = new Uint8Array(head);
  if (bytes.includes(0)) {
    return { ok: false, reason: "二进制文件请在桌面端附加（将驻留到工作区）" };
  }
  const text = new TextDecoder("utf-8").decode(
    bytes.subarray(0, Math.min(bytes.length, TEXT_PREVIEW_CAP)),
  );
  return {
    ok: true,
    attachment: {
      name: file.name,
      path: file.name,
      text,
      truncated: file.size > TEXT_PREVIEW_CAP,
      kind: "file",
    },
  };
}
