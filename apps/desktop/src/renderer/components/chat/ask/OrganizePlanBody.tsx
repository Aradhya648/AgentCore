/**
 * organize_plan — 整理方案清单：原路径→新路径，默认全选，取消勾选即剔除。
 */
import { MANUAL_HELP, ManualHelpLink } from "@/components/ManualHelpLink";
import { Button } from "@/components/ui";
import type { CheckpointUserDecision } from "@/services/checkpoint";
import type { AskOption } from "@/types/events";
import { Check, FolderTree, Loader2, OctagonX } from "lucide-react";
import type { AskUserContent } from "./AskUserFields";
import type { useAskAnswer } from "./AskUserFields";

function summarizeOps(options: AskOption[]): string {
  let mkdir = 0;
  let move = 0;
  let copy = 0;
  let del = 0;
  for (const o of options) {
    const op = o.op;
    if (op === "mkdir") mkdir += 1;
    else if (op === "move") move += 1;
    else if (op === "copy") copy += 1;
    else if (op === "delete") del += 1;
  }
  const parts: string[] = [];
  if (mkdir) parts.push(`新建 ${mkdir} 个文件夹`);
  if (move) parts.push(`移动 ${move} 个文件`);
  if (copy) parts.push(`复制 ${copy} 个文件`);
  if (del) parts.push(`删除 ${del} 项（进回收站）`);
  return parts.length ? parts.join("、") : `${options.length} 项整理操作`;
}

export function OrganizePlanBody({
  content,
  answer,
  busy,
  submitting,
  caption,
  cta,
  onContinue,
  onStop,
}: {
  content: AskUserContent;
  answer: ReturnType<typeof useAskAnswer>;
  busy: boolean;
  submitting: CheckpointUserDecision | null;
  caption: string;
  cta: string;
  onContinue: () => void;
  onStop: () => void;
}) {
  const q = content.questions[0];
  const picked = q ? (answer.answers[q.id] ?? []) : [];
  const overview = q ? summarizeOps(q.options) : "";

  return (
    <>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto px-3 pt-3">
        <div className="flex items-start gap-1.5">
          <FolderTree
            size={14}
            className="mt-0.5 shrink-0 text-muted-foreground"
          />
          <div className="min-w-0 flex-1">
            <div className="flex items-center gap-1">
              <p className="min-w-0 flex-1 text-xs font-medium text-muted-foreground">
                {caption}
              </p>
              <ManualHelpLink to={MANUAL_HELP.checkpoint} />
            </div>
            <p className="mt-0.5 whitespace-pre-wrap text-sm text-foreground">
              {content.question}
            </p>
            {content.context && (
              <p className="mt-1 whitespace-pre-wrap text-xs text-muted-foreground">
                {content.context}
              </p>
            )}
            {overview && (
              <p className="mt-1.5 text-xs text-muted-foreground">
                总览：{overview}
                <span className="ml-1 text-muted-foreground/80">
                  （敏感命名启发式默认已剔除，可勾回；非安全边界）
                </span>
              </p>
            )}
          </div>
        </div>

        {q && (
          <div className="space-y-1.5" data-ask-variant="organize_plan">
            {q.prompt && (
              <div className="flex items-center gap-2">
                <p className="min-w-0 flex-1 text-xs font-medium text-muted-foreground">
                  {q.prompt}
                </p>
                <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                  取消勾选即剔除
                </span>
              </div>
            )}
            {q.options.map((opt) => (
              <OrganizeRow
                key={opt.label}
                option={opt}
                active={picked.includes(opt.label)}
                disabled={busy}
                onToggle={() => answer.toggleChoice(q, opt.label)}
              />
            ))}
          </div>
        )}

        <textarea
          value={answer.note}
          onChange={(e) => answer.setNote(e.target.value)}
          disabled={busy}
          rows={2}
          placeholder="补充说明（可选）"
          className="w-full rounded-lg border border-border bg-card px-2.5 py-1.5 text-xs text-foreground placeholder:text-muted-foreground/70 focus:border-foreground/25 focus:outline-none disabled:opacity-40"
        />
      </div>

      <div className="shrink-0 space-y-2 px-3 pb-3 pt-1">
        <div className="flex flex-wrap items-center gap-2">
          <Button
            size="md"
            variant="primary"
            className="bg-primary text-primary-foreground hover:bg-primary/90"
            disabled={busy || picked.length === 0}
            onClick={onContinue}
          >
            {submitting === "continue" ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <Check size={14} />
            )}
            {cta}
            {picked.length > 0 ? `（${picked.length}）` : ""}
          </Button>
          <Button
            size="md"
            variant="ghost"
            disabled={busy}
            onClick={onStop}
            className="text-muted-foreground"
          >
            {submitting === "stop" ? (
              <Loader2 size={14} className="animate-spin" />
            ) : (
              <OctagonX size={14} />
            )}
            停止
          </Button>
        </div>
        <p className="text-xs text-muted-foreground">
          确认后按方案批量执行，不再二次弹审批；完成后可撤销本次 move/mkdir。
        </p>
      </div>
    </>
  );
}

function OrganizeRow({
  option,
  active,
  disabled,
  onToggle,
}: {
  option: AskOption;
  active: boolean;
  disabled: boolean;
  onToggle: () => void;
}) {
  const arrow =
    option.op === "move" || option.op === "copy"
      ? `${option.source ?? "?"} → ${option.destination ?? "?"}`
      : option.path
        ? `${option.op ?? "op"} ${option.path}`
        : null;

  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onToggle}
      className={`flex w-full items-start gap-2 rounded-lg border px-2.5 py-2 text-left transition-colors disabled:opacity-40 ${
        active
          ? "border-foreground/25 bg-accent"
          : "border-border bg-card hover:bg-accent/50"
      }`}
    >
      <span
        className={`mt-0.5 flex h-4 w-4 shrink-0 items-center justify-center rounded border ${
          active
            ? "border-foreground bg-foreground text-background"
            : "border-border"
        }`}
      >
        {active ? <Check size={10} /> : null}
      </span>
      <span className="min-w-0 flex-1">
        <span className="block text-sm text-foreground">{option.label}</span>
        {(arrow || option.detail) && (
          <span className="mt-0.5 block text-xs text-muted-foreground">
            {arrow ?? option.detail}
          </span>
        )}
      </span>
    </button>
  );
}
