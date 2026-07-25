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

/**
 * Shared confirmation when deleting a folder (= 项目).
 * Soft-delete is the default; check the permanent option to hard-delete in the
 * same dialog (no second step / type-to-confirm). Used by
 * {@link WorkspaceSection} and {@link WorkspaceGroupHeader}.
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
  const [permanent, setPermanent] = useState(false);

  useEffect(() => {
    if (!open) return;
    setPermanent(false);
  }, [open]);

  const handleOpenChange = (next: boolean) => {
    if (!next) setPermanent(false);
    onOpenChange(next);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>删除项目「{name}」？</DialogTitle>
          <DialogDescription asChild>
            <div className="space-y-2 text-sm text-muted-foreground">
              {permanent ? (
                <>
                  <p className="text-foreground">
                    将永久删除全部对话与云端文件，不可恢复。
                  </p>
                  {liveConvCount > 0 && (
                    <p>· 含当前可见的 {liveConvCount} 条对话及已归档成员</p>
                  )}
                  {isLocal && (
                    <p>· 本地磁盘上的文件不会被删除（文件在你电脑上）</p>
                  )}
                </>
              ) : (
                <>
                  {liveConvCount > 0 && (
                    <p>其下 {liveConvCount} 条对话将一并归档。</p>
                  )}
                  <p>
                    云端文件约 {FOLDER_FILE_RETENTION_DAYS} 天后由系统自动清理。
                  </p>
                </>
              )}
            </div>
          </DialogDescription>
        </DialogHeader>

        <div className="px-5 pb-1">
          <label className="flex cursor-pointer items-start gap-2 rounded-lg border border-border bg-muted/40 px-3 py-2.5 text-sm text-foreground">
            <input
              type="checkbox"
              className="mt-0.5 size-4 shrink-0 rounded border border-input accent-primary"
              checked={permanent}
              onChange={(e) => setPermanent(e.target.checked)}
            />
            <span>立即永久清除全部对话与云端文件（不可恢复）</span>
          </label>
        </div>

        <DialogFooter>
          <Button variant="neutral" size="md" onClick={() => handleOpenChange(false)}>
            取消
          </Button>
          <Button
            variant="destructive"
            size="md"
            onClick={() =>
              void (permanent ? onPermanentConfirm() : onConfirm())
            }
          >
            {permanent ? "彻底删除" : "删除项目"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
