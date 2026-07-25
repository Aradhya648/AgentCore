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
 * Confirm wiping cloud conversation scratch files (清空本对话产物).
 * Only for `conv:` cloud scratch — not project / local / shared roots.
 */
export function ClearScratchDialog({
  open,
  onOpenChange,
  name,
  busy = false,
  onConfirm,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  name: string;
  busy?: boolean;
  onConfirm: () => void | Promise<void>;
}) {
  const handleOpenChange = (next: boolean) => {
    if (busy && !next) return;
    onOpenChange(next);
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>清空「{name}」的对话产物？</DialogTitle>
          <DialogDescription asChild>
            <div className="space-y-1 text-sm text-muted-foreground">
              <p>将立刻删除本对话工作区下的全部文件，对话本身保留。</p>
              <p>云端产物清空后不可恢复。</p>
            </div>
          </DialogDescription>
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
            {busy ? "清空中…" : "清空产物"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
