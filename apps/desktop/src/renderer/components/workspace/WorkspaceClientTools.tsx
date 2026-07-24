import { IconButton } from "@/components/files/parts";
import type { FileSource } from "@/lib/fileSource";
import { notifyActionError } from "@/lib/toast";
import { openFileSourceShell } from "@/services/terminalActions";
import { FolderOpen, Terminal } from "lucide-react";

/**
 * 对话工作区侧栏的桌面 Client Tools 快捷入口（最小集）：
 * - 打开此对话文件夹（本地绑定工作区 / 裸聊 scratch）
 * - 在终端打开（cd 到工作区根，无命令确认门）
 *
 * Agent 经 `workspace_op` / `code_execute` 的执行链与此正交；这里是用户一键入口。
 */
export function WorkspaceClientTools({
  source,
}: { source: FileSource | null }) {
  if (!source) return null;

  const canReveal = !!source.revealInOsFileManager;
  const canShell = !!source.openShellAtPath;
  if (!canReveal && !canShell) return null;

  const openFolder = async () => {
    try {
      await source.revealInOsFileManager?.("");
    } catch (e) {
      notifyActionError("无法打开文件夹", e);
    }
  };

  const openShell = () => {
    void openFileSourceShell(source, ".");
  };

  return (
    <>
      {canReveal && (
        <IconButton title="打开此对话文件夹" onClick={() => void openFolder()}>
          <FolderOpen size={14} />
        </IconButton>
      )}
      {canShell && (
        <IconButton title="在终端打开" onClick={() => void openShell()}>
          <Terminal size={14} />
        </IconButton>
      )}
    </>
  );
}
