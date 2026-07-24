import type { DownloadedFile, WorkspaceFileEntry } from "@/api/workspace";
import {
  downloadWorkspaceFileByWs,
  listWorkspaceFilesByWs,
  uploadWorkspaceFileByWs,
} from "@/api/workspaces";
import { CollaborationSummaryList } from "@/components/CollaborationSummaryList";
import { FileBrowser, type FileBrowserSource } from "@/components/FileBrowser";
// Browse ONE cloud workspace's files (手机端布局重构 · 跨工作区文件总览).
//
// The drill-down from the 文件 tab (/files → /files/:wsId). Keeps the bottom tab bar (a
// within-tab push), with a 「← 文件」back to the workspace list. Renders the shared
// <FileBrowser> over a first-class workspace source (api/workspaces.ts), the cross-workspace
// sibling of the per-conversation /c/:id/files. The workspace name rides in router state from
// the list so the header shows it without a refetch.
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate, useParams } from "react-router-dom";

export function WorkspaceFilesPage() {
  const navigate = useNavigate();
  const location = useLocation();
  const { wsId = "" } = useParams<{ wsId: string }>();
  const name = (location.state as { name?: string } | null)?.name ?? "工作区";

  const [cwd, setCwd] = useState("");
  const [reloadKey, setReloadKey] = useState(0);
  const [uploading, setUploading] = useState(false);
  const [uploadError, setUploadError] = useState<string | null>(null);
  const uploadInputRef = useRef<HTMLInputElement>(null);

  // Reset to root when switching to a different workspace (the component is reused across
  // /files/:wsId param changes, so state would otherwise leak across workspaces).
  // biome-ignore lint/correctness/useExhaustiveDependencies: wsId is the intentional trigger — the reset must run on every workspace switch even though the body doesn't read it
  useEffect(() => {
    setCwd("");
    setUploadError(null);
  }, [wsId]);

  const source = useMemo<FileBrowserSource>(
    () => ({
      list: (): Promise<WorkspaceFileEntry[]> => listWorkspaceFilesByWs(wsId),
      download: (path: string): Promise<DownloadedFile> =>
        downloadWorkspaceFileByWs(wsId, path),
    }),
    [wsId],
  );

  const onPickUpload = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      e.target.value = "";
      if (!file || !wsId) return;
      const target = cwd ? `${cwd}/${file.name}` : file.name;
      setUploading(true);
      setUploadError(null);
      try {
        await uploadWorkspaceFileByWs(wsId, target, file);
        setReloadKey((k) => k + 1);
      } catch (err) {
        setUploadError(err instanceof Error ? err.message : "上传失败");
      } finally {
        setUploading(false);
      }
    },
    [wsId, cwd],
  );

  return (
    <div className="screen">
      <header className="bar">
        <button
          type="button"
          className="link"
          onClick={() => navigate("/files")}
        >
          ← 文件
        </button>
        <span className="viewer-name">{name}</span>
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

      <CollaborationSummaryList wsId={wsId} />

      <FileBrowser
        source={source}
        cwd={cwd}
        onCwdChange={setCwd}
        reloadKey={reloadKey}
        emptyHint="此工作区还没有文件。"
      />

      {uploadError && <div className="error bar">{uploadError}</div>}
    </div>
  );
}
