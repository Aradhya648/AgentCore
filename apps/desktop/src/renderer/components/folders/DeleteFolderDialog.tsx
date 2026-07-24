import { Button } from "@/components/ui";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { Conversation } from "@/stores/conversation";
import { useEffect, useState } from "react";

/** Matches server retention default (双模式工作区 §七). */
export const FOLDER_FILE_RETENTION_DAYS = 30;

/**
 * Archive each conversation in `convs` before deleting the folder. Returns false
 * on the first failure (caller should abort delete).
 */
export async function archiveConversationsBeforeDelete(
  convs: Conversation[],
  {
    archive,
    dropRuntime,
    currentId,
    onLeaveActive,
  }: {
    archive: (id: string) => Promise<unknown>;
    dropRuntime: (id: string) => void;
    currentId: string | null;
    onLeaveActive: () => void;
  },
): Promise<boolean> {
  for (const { id } of convs) {
    try {
      await archive(id);
      dropRuntime(id);
      if (id === currentId) onLeaveActive();
    } catch {
      return false;
    }
  }
  return true;
}

type DialogPhase = "soft" | "permanent";

/**
 * Shared confirmation when deleting a folder (= 项目).
 * Soft-delete is the default; permanent delete is a second confirmation step
 * (no type-to-confirm). Used by {@link WorkspaceSection} and
 * {@link WorkspaceGroupHeader}.
 */
export function DeleteFolderDialog({
  open,
  onOpenChange,
  name,
  liveConvCount,
  isLocal = false,
  onConfirm,
  onPermanentConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  name: string;
  liveConvCount: number;
  isLocal?: boolean;
  onConfirm: () => void | Promise<void>;
  onPermanentConfirm: () => void | Promise<void>;
}) {
  const [phase, setPhase] = useState<DialogPhase>("soft");

  useEffect(() => {
    if (!open) return;
    setPhase("soft");
  }, [open]);

  const handleOpenChange = (next: boolean) => {
    if (!next) setPhase("soft");
    onOpenChange(next);
  };

  if (phase === "permanent") {
    return (
      <Dialog open={open} onOpenChange={handleOpenChange}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>彻底删除项目「{name}」？</DialogTitle>
            <DialogDescription asChild>
              <div className="space-y-2 text-sm text-muted-foreground">
                <p className="text-foreground">
                  将永久删除全部对话与云端文件，不可恢复。
                </p>
                {liveConvCount > 0 && (
                  <p>· 含当前可见的 {liveConvCount} 条对话及已归档成员</p>
                )}
                {isLocal && (
                  <p>· 本地磁盘上的文件不会被删除（文件在你电脑上）</p>
                )}
              </div>
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button
              variant="neutral"
              className="h-9 px-4"
              onClick={() => setPhase("soft")}
            >
              返回
            </Button>
            <Button
              variant="danger"
              className="h-9 px-4"
              onClick={() => void onPermanentConfirm()}
            >
              彻底删除
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    );
  }

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>删除项目「{name}」？</DialogTitle>
          <DialogDescription asChild>
            <div className="space-y-1 text-sm text-muted-foreground">
              {liveConvCount > 0 && (
                <p>其下 {liveConvCount} 条对话将一并归档。</p>
              )}
              <p>
                云端文件约 {FOLDER_FILE_RETENTION_DAYS} 天后由系统自动清理。
              </p>
            </div>
          </DialogDescription>
        </DialogHeader>
        <DialogFooter className="flex-col gap-3 sm:flex-col sm:space-x-0">
          <div className="flex w-full justify-end gap-2">
            <Button
              variant="neutral"
              className="h-9 px-4"
              onClick={() => handleOpenChange(false)}
            >
              取消
            </Button>
            <Button
              variant="danger"
              className="h-9 px-4"
              onClick={() => void onConfirm()}
            >
              删除项目
            </Button>
          </div>
          <button
            type="button"
            onClick={() => setPhase("permanent")}
            className="text-center text-muted-foreground text-xs hover:text-foreground"
          >
            需要立即清除全部数据？
          </button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
