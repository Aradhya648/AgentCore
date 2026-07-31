import { Button, Input, Textarea } from "@/components/ui";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { notifyError, notifySuccess } from "@/lib/toast";
import { APP_PATHS } from "@/pages/toolbox/manual/paths";
import { ApiError } from "@/services/api";
import {
  type WorkflowTemplate,
  createWorkflowFromPlaybook,
} from "@/services/workflows";
import { Copy, Loader2 } from "lucide-react";
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";

function errMsg(e: unknown, fallback: string): string {
  return e instanceof ApiError ? (e.serverMessage ?? fallback) : fallback;
}

/**
 * 「使用」官方模板 → 收主槽 → from-playbook → 跳转新工作流画布。
 */
export function UseTemplateDialog({
  open,
  template,
  onClose,
}: {
  open: boolean;
  template: WorkflowTemplate | null;
  onClose: () => void;
}) {
  const navigate = useNavigate();
  const [name, setName] = useState("");
  const [slotValues, setSlotValues] = useState<Record<string, string>>({});
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open || !template) return;
    setName(template.title);
    const next: Record<string, string> = {};
    for (const s of template.slots) next[s.key] = "";
    setSlotValues(next);
    setError(null);
  }, [open, template]);

  if (!template) return null;

  const missingRequired = template.slots.some(
    (s) => s.required && !(slotValues[s.key] ?? "").trim(),
  );

  const submit = async () => {
    if (missingRequired || submitting) return;
    setSubmitting(true);
    setError(null);
    try {
      const created = await createWorkflowFromPlaybook({
        playbook: template.id,
        name: name.trim() || template.title,
        slots: slotValues,
      });
      notifySuccess("已复制为我的工作流");
      onClose();
      navigate(APP_PATHS.toolbox.workflows.edit(created.id));
    } catch (e) {
      setError(errMsg(e, "复制失败"));
      notifyError(e, "复制失败");
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
        <DialogTitle>使用 · {template.title}</DialogTitle>
        <DialogDescription>
          填写主参数后复制为我的工作流，可再在画布里改。
        </DialogDescription>

        <div className="mt-4 space-y-3">
          <label className="block" htmlFor="wf-tpl-name">
            <span className="mb-1 block text-xs text-muted-foreground">
              工作流名称
            </span>
            <Input
              id="wf-tpl-name"
              className="w-full"
              value={name}
              maxLength={200}
              onChange={(e) => setName(e.target.value)}
            />
          </label>

          {template.slots.map((slot) => {
            const id = `wf-tpl-slot-${slot.key}`;
            const value = slotValues[slot.key] ?? "";
            return (
              <label key={slot.key} className="block" htmlFor={id}>
                <span className="mb-1 block text-xs text-muted-foreground">
                  {slot.label}
                  {slot.required ? "" : "（可选）"}
                </span>
                <Textarea
                  id={id}
                  className="w-full text-sm"
                  rows={3}
                  value={value}
                  maxLength={4000}
                  placeholder={slot.hint ?? undefined}
                  onChange={(e) =>
                    setSlotValues((prev) => ({
                      ...prev,
                      [slot.key]: e.target.value,
                    }))
                  }
                />
              </label>
            );
          })}

          {error && <p className="text-xs text-destructive">{error}</p>}
        </div>

        <div className="mt-5 flex justify-end gap-2">
          <Button variant="neutral" size="md" onClick={onClose}>
            取消
          </Button>
          <Button
            size="md"
            disabled={missingRequired || submitting}
            icon={
              submitting ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <Copy size={14} />
              )
            }
            onClick={() => void submit()}
          >
            复制为我的
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
