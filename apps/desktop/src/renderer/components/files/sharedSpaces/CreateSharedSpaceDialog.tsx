import { Button, Input } from "@/components/ui";
import {
  Dialog,
  DialogContent,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import { useCreateSharedSpace } from "@/hooks/useSharedSpaces";
import { notifyError, notifySuccess } from "@/lib/toast";
import { useEffect, useState } from "react";

/**
 * Create a new shared space (owner = current user). Name is the only field in v1.
 */
export function CreateSharedSpaceDialog({
  open,
  onClose,
  onCreated,
}: {
  open: boolean;
  onClose: () => void;
  onCreated?: (spaceId: string) => void;
}) {
  const [name, setName] = useState("");
  const create = useCreateSharedSpace();

  useEffect(() => {
    if (!open) return;
    setName("");
  }, [open]);

  const submit = () => {
    const trimmed = name.trim();
    if (!trimmed || create.isPending) return;
    create.mutate(trimmed, {
      onSuccess: (space) => {
        notifySuccess(`已创建共享空间「${space.name}」`);
        onCreated?.(space.id);
        onClose();
      },
      onError: (err) => notifyError(err, "创建共享空间失败"),
    });
  };

  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent
        position="top"
        className="max-w-md"
        aria-describedby={undefined}
      >
        <DialogHeader>
          <DialogTitle>新建共享空间</DialogTitle>
          <p className="text-sm text-muted-foreground">
            成员共见同一份文件；可编辑成员的 Agent 可直接写入。
          </p>
        </DialogHeader>
        <div className="px-5">
          <Input
            autoFocus
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="空间名称"
            aria-label="空间名称"
            maxLength={200}
            onKeyDown={(e) => {
              if (e.key === "Enter") {
                e.preventDefault();
                submit();
              }
            }}
          />
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={onClose}>
            取消
          </Button>
          <Button disabled={!name.trim() || create.isPending} onClick={submit}>
            {create.isPending ? "创建中…" : "创建"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
