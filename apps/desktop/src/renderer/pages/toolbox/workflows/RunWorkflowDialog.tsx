import { Button, Textarea } from "@/components/ui";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { notifyError, notifySuccess } from "@/lib/toast";
import { ApiError } from "@/services/api";
import { type FolderMeta, listFolders } from "@/services/folders";
import { runWorkflow } from "@/services/workflows";
import { Loader2, Play } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

const SELECT_CLASS =
  "h-8 w-full rounded-lg border border-border bg-background px-2.5 text-sm text-foreground focus:border-primary focus:outline-none focus:ring-1 focus:ring-ring";

function errMsg(e: unknown, fallback: string): string {
  return e instanceof ApiError ? (e.serverMessage ?? fallback) : fallback;
}

export function RunWorkflowDialog({
  open,
  workflowId,
  workflowName,
  onClose,
}: {
  open: boolean;
  workflowId: string;
  workflowName: string;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const [folders, setFolders] = useState<FolderMeta[]>([]);
  const [folderId, setFolderId] = useState("");
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    setNote("");
    setError(null);
    void listFolders()
      .then((all) => {
        const cloud = all.filter((f) => f.mode === "cloud");
        const any = cloud.length > 0 ? cloud : all;
        setFolders(any);
        setFolderId(any[0]?.id ?? "");
      })
      .catch(() => {
        setFolders([]);
        setFolderId("");
      });
  }, [open]);

  const submit = async () => {
    if (!folderId || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const result = await runWorkflow(workflowId, {
        folderId,
        note: note.trim() || null,
      });
      notifySuccess("已按工作流开跑");
      onClose();
      if (result.conversationId) {
        navigate(`/conversations/${result.conversationId}`);
      }
    } catch (e) {
      setError(errMsg(e, "跑一次失败"));
      notifyError(e, "跑一次失败");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <DialogContent className="max-w-md">
        <DialogTitle>跑一次 · {workflowName}</DialogTitle>
        <DialogDescription>
          选择工作区后按保存的图直起；可选填本轮补充说明（不改图）。
        </DialogDescription>

        <div className="mt-4 space-y-3">
          <label className="block">
            <span className="mb-1 block text-xs text-muted-foreground">
              工作区
            </span>
            <select
              className={SELECT_CLASS}
              value={folderId}
              disabled={folders.length === 0}
              onChange={(e) => setFolderId(e.target.value)}
            >
              {folders.length === 0 ? (
                <option value="">暂无可用工作区</option>
              ) : (
                folders.map((f) => (
                  <option key={f.id} value={f.id}>
                    {f.name}
                    {f.mode === "cloud" ? "" : "（本地）"}
                  </option>
                ))
              )}
            </select>
          </label>

          <label className="block" htmlFor="wf-run-note">
            <span className="mb-1 block text-xs text-muted-foreground">
              本轮补充（可选）
            </span>
            <Textarea
              id="wf-run-note"
              className="w-full text-sm"
              rows={3}
              value={note}
              maxLength={4000}
              placeholder="空则只按图跑；有则作为本轮附加上下文"
              onChange={(e) => setNote(e.target.value)}
            />
          </label>

          {error && <p className="text-xs text-destructive">{error}</p>}
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <Button variant="neutral" size="md" onClick={onClose}>
            取消
          </Button>
          <Button
            size="md"
            disabled={!folderId || submitting}
            icon={
              submitting ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Play size={14} />
              )
            }
            onClick={() => void submit()}
          >
            开跑
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
