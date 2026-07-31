import { Button } from "@/components/ui";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/**
 * 关用户终端 confirmOnKill（对齐 VS Code）：busy 会话 / 关 tab 时确认终止。
 * 复用 ClearScratchDialog 同款 Dialog 模式。
 */
export function KillPtyConfirmDialog({
  open,
  onOpenChange,
  description,
  busy = false,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** 说明关闭后果（单会话 / N 个会话）。 */
  description: string;
  busy?: boolean;
  onConfirm: () => void | Promise<void>;
}) {
  const handleOpenChange = (next: boolean) => {
    if (busy && !next) return;
    onOpenChange(next);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent showClose={!busy}>
        <DialogHeader>
          <DialogTitle>要终止正在运行的进程吗？</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            variant="neutral"
            size="md"
            disabled={busy}
            onClick={() => onOpenChange(false)}
          >
            取消
          </Button>
          <Button
            variant="destructive"
            size="md"
            disabled={busy}
            onClick={() => void onConfirm()}
          >
            {busy ? "终止中…" : "终止"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
