import { FileWorkbench } from "@/components/files/FileWorkbench";
import { useWorkspaces } from "@/hooks/useWorkspaces";
import { hasLocalFiles } from "@/lib/capabilities";
import { useMemo } from "react";
import { useLocation } from "react-router-dom";

/**
 * The 文件 hub (跨工作区文件总览) — one place to browse files across every
 * workspace root (`folder:<id>` 项目 + `shared:<id>` 共享空间混排 + `conv:<id>` 裸聊 scratch，云 + 本地)
 * without first opening a conversation. Layout is VSCode 式左树右详情: the left
 * rail stacks each root as a flat, collapsible section over its own
 * {@link FileSource}.
 *
 * 项目（Folder）生命周期删除入口在本页各 `folder:` 根的右键菜单；对话列表页
 * `/conversations` 只做归档与引导。`/conversations`「浏览文件」jumps here with
 * `focusWsId`（`folder:<id>` 或 `conv:<id>`）so the target section expands + highlights.
 */
export function FilesPage() {
  const location = useLocation();
  const query = useWorkspaces();
  const workspaces = useMemo(() => query.data ?? [], [query.data]);

  const focusWsId =
    (location.state as { focusWsId?: string } | null)?.focusWsId ?? null;

  const openMemoryLeaf =
    (
      location.state as {
        openMemoryLeaf?: {
          path: string;
          name: string;
          projectId?: string | null;
        };
      } | null
    )?.openMemoryLeaf ?? null;

  return (
    <FileWorkbench
      workspaces={workspaces}
      isLoading={query.isLoading}
      isError={query.isError}
      onRetry={() => void query.refetch()}
      fsAvailable={hasLocalFiles()}
      showMemory
      focusWsId={focusWsId}
      openMemoryLeaf={openMemoryLeaf}
      focusKey={location.key}
    />
  );
}
