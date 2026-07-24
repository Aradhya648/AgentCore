import {
  type DownloadedFile,
  type WorkspaceFileEntry,
  downloadWorkspaceFile,
  listWorkspaceFiles,
  uploadWorkspaceFile,
} from "@/api/workspace";
import { FileBrowser, type FileBrowserSource } from "@/components/FileBrowser";
// The cloud workspace file browser for ONE conversation (前端技术与架构 §七 · 云端文件浏览).
//
// Reachable from the chat header (/c/:id/files) — a full-screen, conversation-scoped shortcut
// (no bottom tab bar). The 文件 tab's cross-workspace browser (/files/:wsId) is the sibling
// surface; both render the shared <FileBrowser>, differing only in addressing (per-conversation
// alias here, first-class workspace id there) and this page's header / back target. A 裸聊 with
// no workspace yields an empty list.
import { useCallback, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";

export function FilesPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { id: conversationId } = useParams<{ id: string }>();
  // 一键直达：从聊天「本回合产出文件」卡跳来时带着要打开的文件路径（router state）。
  const openPath =
    (location.state as { openPath?: string } | null)?.openPath ?? null;
  const [cwd, setCwd] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const uploadInputRef = useRef<HTMLInputElement>(null);

  // The conversation's workspace as a FileBrowser source — stable per conversation so the
  // browser resets to root only when the conversation changes (not on an upload reload).
  const source = useMemo<FileBrowserSource>(
    () => ({
      list: (): Promise<WorkspaceFileEntry[]> =>
        listWorkspaceFiles(conversationId ?? ""),
      download: (path: string): Promise<DownloadedFile> =>
        downloadWorkspaceFile(conversationId ?? "", path),
    }),
    [conversationId],
  );

  const onPickUpload = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      e.target.value = ""; // allow re-picking the same file after an error
      if (!file || !conversationId) return;
      const target = cwd ? `${cwd}/${file.name}` : file.name;
      setUploading(true);
      setUploadError(null);
      try {
        await uploadWorkspaceFile(conversationId, target, file);
        setReloadKey((k) => k + 1); // refresh so the new file shows in the current folder
      } catch (err) {
        setUploadError(err instanceof Error ? err.message : "上传失败");
      } finally {
        setUploading(false);
      }
    },
    [conversationId, cwd],
  );

  return (
    <div className="screen">
      <header className="bar">
        <button
          type="button"
          className="link"
          onClick={() => navigate(`/c/${conversationId}`)}
        >
          ← 返回
        </button>
        <span>文件</span>
        <button
          type="button"
          className="link"
          onClick={() => uploadInputRef.current?.click()}
          disabled={uploading}
        >
          {uploading ? "上传中…" : "上传"}
        </button>
        <input
          ref={uploadInputRef}
          type="file"
          style={{ display: "none" }}
          onChange={(e) => void onPickUpload(e)}
        />
      </header>

      <FileBrowser
        source={source}
        cwd={cwd}
        onCwdChange={setCwd}
        reloadKey={reloadKey}
        openPath={openPath}
        emptyHint="此对话还没有工作区文件。"
      />

      {uploadError && <div className="error bar">{uploadError}</div>}
    </div>
  );
}
