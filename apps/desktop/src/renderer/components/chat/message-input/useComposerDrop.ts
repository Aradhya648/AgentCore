import { hasLocalFiles } from "@/lib/capabilities";
import {
  type Dispatch,
  type SetStateAction,
  useCallback,
  useEffect,
  useRef,
  useState,
} from "react";
import type { PendingAttachment } from "./composerAttachments";
import {
  prepareBrowserFileAttachment,
  stageDroppedFileAttachment,
} from "./resideAttachment";

/** Soft attach errors: auto-dismiss (Slack / Linear style), not sticky form validation. */
const DROP_ERROR_MS = 4000;

export function useComposerDrop(
  isGenerating: boolean,
  attachments: PendingAttachment[],
  setAttachments: Dispatch<SetStateAction<PendingAttachment[]>>,
  conversationId: string | null = null,
) {
  const [dragOver, setDragOver] = useState(false);
  const [dropError, setDropError] = useState<string | null>(null);
  const dropErrorTimer = useRef<number | null>(null);

  const clearDropError = useCallback(() => {
    if (dropErrorTimer.current) {
      window.clearTimeout(dropErrorTimer.current);
      dropErrorTimer.current = null;
    }
    setDropError(null);
  }, []);

  const flashDropError = useCallback((msg: string) => {
    setDropError(msg);
    if (dropErrorTimer.current) window.clearTimeout(dropErrorTimer.current);
    dropErrorTimer.current = window.setTimeout(() => {
      dropErrorTimer.current = null;
      setDropError(null);
    }, DROP_ERROR_MS);
  }, []);

  // Timer lives in the hook: only clear on unmount. Do NOT wire this to a
  // recreated `drop` object in the parent — that cancelled auto-dismiss on every
  // setDropError re-render and left the red banner stuck.
  useEffect(() => {
    return () => {
      if (dropErrorTimer.current) window.clearTimeout(dropErrorTimer.current);
    };
  }, []);

  const attachDroppedFile = useCallback(
    async (file: File) => {
      const key = `dropped:${file.name}:${file.size}`;
      if (attachments.some((a) => a.key === key)) return;

      // 桌面 Electron：主进程驻留（含二进制 / 区外路径）；绝对路径不进 renderer 状态。
      if (hasLocalFiles()) {
        const res = await stageDroppedFileAttachment(conversationId, file);
        if (!res.ok) {
          flashDropError(res.reason);
          return;
        }
        setAttachments((prev) => [
          ...prev,
          {
            id: crypto.randomUUID(),
            key,
            name: res.name,
            path: res.path,
            text: res.text,
            truncated: res.truncated,
            kind: "file",
            workspacePath: res.workspacePath,
            stagingId: res.stagingId,
            binary: res.binary,
          },
        ]);
        return;
      }

      // 浏览器：回形针 / 拖 / 贴共用 prepare → 立即 PUT 或持 fileBlob。
      const res = await prepareBrowserFileAttachment(conversationId, file);
      if (!res.ok) {
        flashDropError(res.reason);
        return;
      }
      setAttachments((prev) => [
        ...prev,
        {
          id: crypto.randomUUID(),
          key,
          name: res.name,
          path: res.path,
          text: res.text,
          truncated: res.truncated,
          kind: "file",
          workspacePath: res.workspacePath,
          binary: res.binary,
          ...(res.fileBlob ? { fileBlob: res.fileBlob } : {}),
        },
      ]);
    },
    [attachments, conversationId, flashDropError, setAttachments],
  );

  const handleDragOver = useCallback(
    (e: React.DragEvent) => {
      if (isGenerating || !e.dataTransfer.types.includes("Files")) return;
      e.preventDefault();
      setDragOver(true);
    },
    [isGenerating],
  );

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    if (e.currentTarget.contains(e.relatedTarget as Node | null)) return;
    setDragOver(false);
  }, []);

  // 粘贴入框: Ctrl/Cmd+V of a file (or a screenshot) attaches via the SAME path as drop.
  const handlePaste = useCallback(
    (e: React.ClipboardEvent) => {
      if (isGenerating) return;
      const files = Array.from(e.clipboardData?.files ?? []);
      if (files.length === 0) return;
      e.preventDefault();
      void (async () => {
        for (const f of files) await attachDroppedFile(f);
      })();
    },
    [isGenerating, attachDroppedFile],
  );

  const handleDrop = useCallback(
    async (e: React.DragEvent) => {
      if (!e.dataTransfer.types.includes("Files")) return;
      e.preventDefault();
      setDragOver(false);
      if (isGenerating) return;
      // New drop attempt: clear prior soft error so feedback matches this action.
      clearDropError();
      const dropped: File[] = [];
      let sawDir = false;
      const items = Array.from(e.dataTransfer.items ?? []);
      if (items.length) {
        for (const item of items) {
          if (item.kind !== "file") continue;
          if (item.webkitGetAsEntry?.()?.isDirectory) {
            sawDir = true;
            continue;
          }
          const f = item.getAsFile();
          if (f) dropped.push(f);
        }
      } else {
        dropped.push(...Array.from(e.dataTransfer.files));
      }
      for (const f of dropped) await attachDroppedFile(f);
      if (sawDir) flashDropError("文件夹请用 @ 引用，拖拽仅支持文件");
    },
    [isGenerating, attachDroppedFile, clearDropError, flashDropError],
  );

  return {
    dragOver,
    dropError,
    clearDropError,
    attachDroppedFile,
    handleDragOver,
    handleDragLeave,
    handleDrop,
    handlePaste,
  };
}
