import { IconButton } from "@/components/files/parts";
import type { FileSource } from "@/lib/fileSource";
import { notifyActionError } from "@/lib/toast";
import { FolderOpen } from "lucide-react";

/**
 * 对话工作区侧栏的桌面 Client Tools 快捷入口（最小集）：
 * - 打开此对话文件夹（本地绑定工作区 / 裸聊 scratch）
 *
 * 「在终端打开」不放标题栏（与侧栏「终端」tab 易混）；外置终端走文件树右键 / 命令面板。
 * Agent 经 `workspace_op` / `code_execute` 的执行链与此正交；这里是用户一键入口。
 */
export function WorkspaceClientTools({
  source,
}: { source: FileSource | null }) {
  if (!source?.revealInOsFileManager) return null;

  const openFolder = async () => {
    try {
      await source.revealInOsFileManager?.("");
    } catch (e) {
      notifyActionError("无法打开文件夹", e);
    }
  };

  return (
    <IconButton title="打开此对话文件夹" onClick={() => void openFolder()}>
      <FolderOpen size={14} />
    </IconButton>
  );
}
