import { Button, Input, Textarea } from "@/components/ui";
import { IconButton } from "@/components/ui/icon-button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
} from "@/components/ui/dialog";
import { Switch } from "@/components/ui/Switch";
import { copyText } from "@/lib/clipboard";
import { notifyError, notifySuccess } from "@/lib/toast";
import { cn } from "@/lib/utils";
import { ApiError } from "@/services/api";
import { type FolderMeta } from "@/services/folders";
import {
  type AutonomyRecipe,
  RECIPE_LABELS,
  RECIPE_ORDER,
  matchRecipe,
  recipeToAxes,
} from "@/services/permissionAxes";
import {
  type CreateStandingTaskInput,
  type StandingTask,
  type TriggerKind,
  SCHEDULE_PRESET_LABELS,
  SCHEDULE_PRESET_ORDER,
  TRIGGER_KIND_LABELS,
  TRIGGER_KIND_ORDER,
  type SchedulePreset,
  createStandingTask,
  patchStandingTask,
  rotateWebhookSecret,
} from "@/services/standingTasks";
import {
  Check,
  Copy,
  KeyRound,
  Loader2,
  Play,
  X,
} from "lucide-react";
import { useEffect, useMemo, useState } from "react";

const SELECT_CLASS =
  "h-8 w-full rounded-lg border border-border bg-background px-2.5 text-sm text-foreground focus:border-primary focus:outline-none focus:ring-1 focus:ring-ring";

function errMsg(e: unknown, fallback: string): string {
  return e instanceof ApiError ? (e.serverMessage ?? fallback) : fallback;
}

export interface StandingTaskFormState {
  name: string;
  triggerKind: TriggerKind;
  schedulePreset: SchedulePreset;
  cron: string;
  folderId: string;
  goal: string;
  recipe: AutonomyRecipe;
  enabled: boolean;
  webhookUrl: string | null;
  webhookId: string | null;
  /** Ephemeral one-shot secret from create / rotate. */
  revealedSecret: string | null;
}

export function emptyStandingTaskForm(
  cloudFolders: FolderMeta[],
): StandingTaskFormState {
  return {
    name: "",
    triggerKind: "schedule",
    schedulePreset: "weekly_mon",
    cron: "",
    folderId: cloudFolders[0]?.id ?? "",
    goal: "",
    recipe: "write_code",
    enabled: true,
    webhookUrl: null,
    webhookId: null,
    revealedSecret: null,
  };
}

export function formFromStandingTask(task: StandingTask): StandingTaskFormState {
  const recipe = matchRecipe(task.permissionAxes);
  return {
    name: task.name,
    triggerKind: task.triggerKind,
    schedulePreset: task.schedulePreset ?? "weekly_mon",
    cron: task.cron ?? "",
    folderId: task.folderId,
    goal: task.goal,
    recipe: recipe === "custom" ? "write_code" : recipe,
    enabled: task.enabled,
    webhookUrl: task.webhookUrl,
    webhookId: task.webhookId,
    revealedSecret: task.webhookSecret,
  };
}

function applyTriggerKind(
  form: StandingTaskFormState,
  kind: TriggerKind,
): StandingTaskFormState {
  if (kind === form.triggerKind) return form;
  if (kind === "webhook") {
    return {
      ...form,
      triggerKind: "webhook",
      schedulePreset: "weekly_mon",
      cron: "",
    };
  }
  return {
    ...form,
    triggerKind: "schedule",
    webhookUrl: null,
    webhookId: null,
    revealedSecret: null,
  };
}

async function copyField(label: string, value: string) {
  const ok = await copyText(value);
  if (ok) notifySuccess(`已复制${label}`);
  else notifyError(`复制${label}失败`);
}

/**
 * 创建/编辑站立任务抽屉（从列表抽出，避免整页内联表单）。
 */
export function StandingTaskEditorDrawer({
  open,
  mode,
  initial,
  taskId,
  cloudFolders,
  onClose,
  onSaved,
}: {
  open: boolean;
  mode: "create" | "edit";
  initial: StandingTaskFormState;
  taskId: string | null;
  cloudFolders: FolderMeta[];
  onClose: () => void;
  onSaved: () => Promise<void>;
}) {
  const [form, setForm] = useState<StandingTaskFormState>(initial);
  const [submitting, setSubmitting] = useState(false);
  const [rotating, setRotating] = useState(false);
  const [error, setError] = useState<string | null>(null);
  /** After create with webhook secret: stay open until user dismisses. */
  const [pendingDismiss, setPendingDismiss] = useState(false);

  useEffect(() => {
    if (!open) return;
    setForm(initial);
    setPendingDismiss(false);
    setError(null);
  }, [initial, open]);

  const noCloud = cloudFolders.length === 0;
  const canSubmit = useMemo(() => {
    if (!form.name.trim() || !form.goal.trim() || !form.folderId) return false;
    if (
      form.triggerKind === "schedule" &&
      form.schedulePreset === "custom" &&
      !form.cron.trim()
    ) {
      return false;
    }
    return true;
  }, [form]);

  const buildPayload = (): CreateStandingTaskInput => {
    const base: CreateStandingTaskInput = {
      name: form.name.trim(),
      triggerKind: form.triggerKind,
      folderId: form.folderId,
      goal: form.goal.trim(),
      permissionAxes: recipeToAxes(form.recipe),
      enabled: form.enabled,
    };
    if (form.triggerKind === "schedule") {
      base.schedulePreset = form.schedulePreset;
      base.cron =
        form.schedulePreset === "custom" ? form.cron.trim() || null : null;
    }
    return base;
  };

  const dismissAfterReveal = async () => {
    setPendingDismiss(false);
    await onSaved();
  };

  const requestClose = () => {
    if (pendingDismiss) {
      void dismissAfterReveal();
      return;
    }
    onClose();
  };

  const submit = async () => {
    if (!canSubmit || submitting) return;
    if (noCloud) {
      setError("请先创建一个云工作区（本地工作区无法在关机时代跑）");
      return;
    }
    setSubmitting(true);
    setError(null);
    const payload = buildPayload();
    try {
      if (mode === "create") {
        const created = await createStandingTask(payload);
        if (created.triggerKind === "webhook" && created.webhookSecret) {
          setForm((f) => ({
            ...f,
            webhookUrl: created.webhookUrl,
            webhookId: created.webhookId,
            revealedSecret: created.webhookSecret,
          }));
          setPendingDismiss(true);
          notifySuccess("任务已创建 — 请复制并妥善保存密钥");
          return;
        }
        notifySuccess("任务已创建");
      } else if (taskId) {
        const patched = await patchStandingTask(taskId, payload);
        if (patched.triggerKind === "webhook" && patched.webhookSecret) {
          setForm((f) => ({
            ...f,
            webhookUrl: patched.webhookUrl ?? f.webhookUrl,
            webhookId: patched.webhookId ?? f.webhookId,
            revealedSecret: patched.webhookSecret,
          }));
          setPendingDismiss(true);
          notifySuccess("已保存 — 请复制并妥善保存密钥");
          return;
        }
        notifySuccess("已保存");
      }
      await onSaved();
    } catch (e) {
      setError(errMsg(e, mode === "create" ? "创建失败" : "保存失败"));
    } finally {
      setSubmitting(false);
    }
  };

  const onRotate = async () => {
    if (!taskId || rotating) return;
    if (!window.confirm("轮换后旧密钥立即失效。确定生成新密钥？")) {
      return;
    }
    setRotating(true);
    setError(null);
    try {
      const result = await rotateWebhookSecret(taskId);
      setForm((f) => ({
        ...f,
        revealedSecret: result.webhookSecret,
        webhookUrl: result.webhookUrl ?? result.task?.webhookUrl ?? f.webhookUrl,
        webhookId: result.webhookId ?? result.task?.webhookId ?? f.webhookId,
      }));
      notifySuccess("密钥已轮换 — 请立即复制新密钥");
    } catch (e) {
      setError(errMsg(e, "轮换密钥失败"));
    } finally {
      setRotating(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) requestClose();
      }}
    >
      <DialogContent
        showClose={false}
        className={cn(
          "fixed inset-y-0 right-0 left-auto top-0 flex h-full max-h-none w-full max-w-lg translate-x-0 translate-y-0 flex-col overflow-hidden rounded-none border-y-0 border-r-0 p-0 shadow-lg",
          "data-[state=open]:animate-none",
        )}
        onPointerDownOutside={(e) => {
          if (pendingDismiss) e.preventDefault();
        }}
        onEscapeKeyDown={(e) => {
          if (pendingDismiss) e.preventDefault();
        }}
      >
        <div className="flex items-start justify-between gap-3 border-b border-border px-5 py-4">
          <div className="min-w-0">
            <DialogTitle className="text-base font-semibold text-foreground">
              {mode === "create" ? "新建任务" : "编辑任务"}
            </DialogTitle>
            <DialogDescription className="mt-1 text-xs text-muted-foreground">
              定时或 Webhook 触发后自动开一轮协作。仅支持云工作区。
            </DialogDescription>
          </div>
          <IconButton
            size="sm"
            aria-label={pendingDismiss ? "完成" : "关闭"}
            onClick={requestClose}
          >
            <X size={16} />
          </IconButton>
        </div>

        <div className="flex-1 space-y-4 overflow-y-auto px-5 py-4">
          {noCloud && (
            <p className="text-xs text-destructive">
              没有可用的云工作区。请先在「文件」页创建云项目，任务不能绑定本地工作区。
            </p>
          )}

          <label className="block" htmlFor="st-name">
            <span className="mb-1 block text-xs text-muted-foreground">名称</span>
            <Input
              id="st-name"
              className="w-full"
              value={form.name}
              maxLength={120}
              placeholder="例如：周一竞品简报"
              disabled={pendingDismiss}
              onChange={(e) => setForm((f) => ({ ...f, name: e.target.value }))}
            />
          </label>

          <fieldset disabled={pendingDismiss}>
            <legend className="mb-1 block text-xs text-muted-foreground">
              触发方式
            </legend>
            <div className="flex flex-wrap gap-2">
              {TRIGGER_KIND_ORDER.map((kind) => (
                <button
                  key={kind}
                  type="button"
                  className={cn(
                    "rounded-lg border px-3 py-1.5 text-sm transition-colors",
                    form.triggerKind === kind
                      ? "border-primary bg-primary/10 text-foreground"
                      : "border-border bg-background text-muted-foreground hover:text-foreground",
                  )}
                  onClick={() => setForm((f) => applyTriggerKind(f, kind))}
                >
                  {TRIGGER_KIND_LABELS[kind]}
                </button>
              ))}
            </div>
            <p className="mt-1 text-xs text-muted-foreground">
              每任务仅一种触发；切换会清空另一方配置。
            </p>
          </fieldset>

          {form.triggerKind === "schedule" && (
            <>
              <label className="block">
                <span className="mb-1 block text-xs text-muted-foreground">
                  周期
                </span>
                <select
                  className={SELECT_CLASS}
                  value={form.schedulePreset}
                  disabled={pendingDismiss}
                  onChange={(e) =>
                    setForm((f) => ({
                      ...f,
                      schedulePreset: e.target.value as SchedulePreset,
                    }))
                  }
                >
                  {SCHEDULE_PRESET_ORDER.map((id) => (
                    <option key={id} value={id}>
                      {SCHEDULE_PRESET_LABELS[id]}
                    </option>
                  ))}
                </select>
              </label>

              {form.schedulePreset === "custom" && (
                <label className="block" htmlFor="st-cron">
                  <span className="mb-1 block text-xs text-muted-foreground">
                    Cron 表达式
                  </span>
                  <Input
                    id="st-cron"
                    className="w-full font-mono"
                    value={form.cron}
                    placeholder="0 9 * * 1"
                    disabled={pendingDismiss}
                    onChange={(e) =>
                      setForm((f) => ({ ...f, cron: e.target.value }))
                    }
                  />
                </label>
              )}
            </>
          )}

          {form.triggerKind === "webhook" && (
            <WebhookCredentialsPanel
              webhookUrl={form.webhookUrl}
              revealedSecret={form.revealedSecret}
              canRotate={mode === "edit" && !!taskId && !pendingDismiss}
              rotating={rotating}
              onRotate={() => void onRotate()}
              hint={
                mode === "create" && !form.revealedSecret
                  ? "创建后将显示 Webhook URL 与一次性密钥，请立即复制保存。"
                  : undefined
              }
            />
          )}

          <label className="block">
            <span className="mb-1 block text-xs text-muted-foreground">
              云工作区
            </span>
            <select
              className={SELECT_CLASS}
              value={form.folderId}
              disabled={noCloud || pendingDismiss}
              onChange={(e) =>
                setForm((f) => ({ ...f, folderId: e.target.value }))
              }
            >
              {cloudFolders.map((f) => (
                <option key={f.id} value={f.id}>
                  {f.name}
                </option>
              ))}
            </select>
          </label>

          <label className="block" htmlFor="st-goal">
            <span className="mb-1 block text-xs text-muted-foreground">目标</span>
            <Textarea
              id="st-goal"
              className="w-full text-sm"
              rows={4}
              value={form.goal}
              maxLength={4000}
              disabled={pendingDismiss}
              placeholder={
                form.triggerKind === "webhook"
                  ? "常驻交代：收到外部事件后要完成什么？事件正文会追加到本轮上下文。"
                  : "到点要完成什么？例如：汇总本周竞品动态与风险，给出三条行动建议。"
              }
              onChange={(e) => setForm((f) => ({ ...f, goal: e.target.value }))}
            />
          </label>

          <label className="block">
            <span className="mb-1 block text-xs text-muted-foreground">自主度</span>
            <select
              className={SELECT_CLASS}
              value={form.recipe}
              disabled={pendingDismiss}
              onChange={(e) =>
                setForm((f) => ({
                  ...f,
                  recipe: e.target.value as AutonomyRecipe,
                }))
              }
            >
              {RECIPE_ORDER.map((id) => (
                <option key={id} value={id}>
                  {RECIPE_LABELS[id].short} — {RECIPE_LABELS[id].description}
                </option>
              ))}
            </select>
          </label>

          <div className="flex items-center justify-between gap-3">
            <div>
              <p className="text-sm font-medium text-foreground">启用</p>
              <p className="text-xs text-muted-foreground">
                {form.triggerKind === "webhook"
                  ? "关闭后外部 POST 不再开跑（可随时打开）。"
                  : "关闭后不再到点触发（可随时打开）。"}
              </p>
            </div>
            <Switch
              checked={form.enabled}
              disabled={pendingDismiss}
              onCheckedChange={(v) => setForm((f) => ({ ...f, enabled: v }))}
              label="启用任务"
            />
          </div>

          {error && <p className="text-xs text-destructive">{error}</p>}
        </div>

        <div className="flex justify-end gap-2 border-t border-border px-5 py-4">
          {pendingDismiss ? (
            <Button
              size="md"
              icon={<Check size={14} />}
              onClick={() => void dismissAfterReveal()}
            >
              已保存密钥，完成
            </Button>
          ) : (
            <>
              <Button variant="neutral" size="md" onClick={onClose}>
                取消
              </Button>
              <Button
                size="md"
                disabled={!canSubmit || submitting || noCloud}
                icon={
                  submitting ? (
                    <Loader2 size={14} className="animate-spin" />
                  ) : mode === "create" ? (
                    <Play size={14} />
                  ) : undefined
                }
                onClick={() => void submit()}
              >
                {mode === "create" ? "创建" : "保存"}
              </Button>
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function WebhookCredentialsPanel({
  webhookUrl,
  revealedSecret,
  canRotate,
  rotating,
  onRotate,
  hint,
}: {
  webhookUrl: string | null;
  revealedSecret: string | null;
  canRotate: boolean;
  rotating: boolean;
  onRotate: () => void;
  hint?: string;
}) {
  return (
    <div className="space-y-3 rounded-lg border border-border bg-muted/30 p-3">
      <p className="text-xs font-medium text-foreground">Webhook 凭证</p>
      {hint && <p className="text-xs text-muted-foreground">{hint}</p>}

      {webhookUrl ? (
        <div>
          <span className="mb-1 block text-xs text-muted-foreground">URL</span>
          <div className="flex gap-1.5">
            <Input
              className="min-w-0 flex-1 font-mono text-xs"
              value={webhookUrl}
              readOnly
            />
            <Button
              variant="neutral"
              size="sm"
              icon={<Copy size={14} />}
              onClick={() => void copyField(" URL", webhookUrl)}
            >
              复制
            </Button>
          </div>
          <p className="mt-1 text-xs text-muted-foreground">
            外部系统 POST 到此地址；鉴权用 Bearer 密钥或{" "}
            <code className="font-mono text-xs">X-AgentCore-Webhook-Secret</code>
            。
          </p>
        </div>
      ) : (
        !revealedSecret && (
          <p className="text-xs text-muted-foreground">
            创建成功后会显示专属 URL。
          </p>
        )
      )}

      {revealedSecret ? (
        <div>
          <span className="mb-1 block text-xs text-muted-foreground">
            密钥（仅显示一次）
          </span>
          <div className="flex gap-1.5">
            <Input
              className="min-w-0 flex-1 font-mono text-xs"
              value={revealedSecret}
              readOnly
            />
            <Button
              variant="neutral"
              size="sm"
              icon={<Copy size={14} />}
              onClick={() => void copyField("密钥", revealedSecret)}
            >
              复制
            </Button>
          </div>
          <p className="mt-1 text-xs text-warning">
            离开本页后无法再次查看明文；请立即复制保存。
          </p>
        </div>
      ) : (
        webhookUrl && (
          <p className="text-xs text-muted-foreground">
            密钥明文不可再次查看。需要新密钥请轮换（旧密钥立即失效）。
          </p>
        )
      )}

      {canRotate && (
        <Button
          variant="neutral"
          size="sm"
          disabled={rotating}
          icon={
            rotating ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <KeyRound size={14} />
            )
          }
          onClick={onRotate}
        >
          轮换密钥
        </Button>
      )}
    </div>
  );
}
