/**
 * 生产通用澄清卡 —— AskCardShell + 行式选项（{@link AskRowGroup}）。
 * Wire `intent=kickoff` 与 `decision` 均挂此体；无开场仪式主 CTA。
 * 彩色「推荐 / 默认」徽章已删：`default` 由 {@link useAskAnswer} 预选，选中态即其表达。
 * 空 `styleOptions` / `formatOptions` 不渲染场面区。
 */
import { MANUAL_HELP, ManualHelpLink } from "@/components/ManualHelpLink";
import { ASK_INTENT_META } from "@/components/chat/decision";
import {
  formatBindLocalFolderAnswer,
  pickAndBindLocalFolder,
} from "@/lib/bindLocalFolder";
import { hasLocalFiles } from "@/lib/capabilities";
import {
  guideDesktopDownload,
  isDesktopFolderAction,
} from "@/lib/desktopDownload";
import {
  formatGrantOrganizeFolderAnswer,
  pickAndGrantOrganizeFolder,
} from "@/lib/grantOrganizeFolder";
import {
  formatGrantReadonlyFolderAnswer,
  pickAndGrantReadonlyFolder,
} from "@/lib/grantReadonlyFolder";
import { pickAndOpenLocalProject } from "@/lib/openLocalProject";
import type { CheckpointUserDecision } from "@/services/checkpoint";
import type { AskOption, AskQuestion } from "@/types/events";
import { ChevronRight, FolderOpen, Loader2, Pencil } from "lucide-react";
import { useState } from "react";
import { useNavigate } from "react-router-dom";
import { AskCardFooter, AskCardShell, AskSectionLabel } from "./AskCardShell";
import { CommenceNote } from "./AskCommenceParts";
import { type AskRow, AskRowGroup } from "./AskOptionRow";
import type { AskUserContent, useAskAnswer } from "./AskUserFields";

const META = ASK_INTENT_META.decision;

export function AskDecisionBody({
  content,
  answer,
  busy,
  submitting,
  caption,
  onContinue,
  onStop,
  conversationId,
  onBindResolve,
}: {
  content: AskUserContent;
  answer: ReturnType<typeof useAskAnswer>;
  busy: boolean;
  submitting: CheckpointUserDecision | null;
  caption?: string;
  onContinue: () => void;
  onStop: () => void;
  conversationId?: string | null;
  onBindResolve?: (composedAnswer: string) => void | Promise<void>;
}) {
  const navigate = useNavigate();
  const [bindBusyLabel, setBindBusyLabel] = useState<string | null>(null);
  const [bindError, setBindError] = useState<string | null>(null);
  const [noteOpen, setNoteOpen] = useState(false);

  const canLocalFs = hasLocalFiles() && !!window.fsApi;
  const canBindAction = !!conversationId && !!onBindResolve && canLocalFs;

  const handleBindOption = async (q: AskQuestion, opt: AskOption) => {
    if (busy || bindBusyLabel) return;

    if (opt.action === "open_local_project") {
      if (!canLocalFs) return;
      setBindBusyLabel(opt.label);
      setBindError(null);
      const result = await pickAndOpenLocalProject(navigate);
      if (!result.ok) {
        if (result.reason === "error") setBindError(result.message);
        else if (result.reason === "unavailable") {
          setBindError("打开本地项目仅桌面端可用");
        }
        setBindBusyLabel(null);
        return;
      }
      // New conversation started — leave this pause as-is (do not rewrite folder_id).
      setBindBusyLabel(null);
      return;
    }

    if (!conversationId || !onBindResolve) return;
    setBindBusyLabel(opt.label);
    setBindError(null);

    if (opt.action === "grant_readonly_folder") {
      const result = await pickAndGrantReadonlyFolder(conversationId);
      if (!result.ok) {
        if (result.reason === "error") setBindError(result.message);
        else if (result.reason === "unavailable") {
          setBindError("区外目录授权仅桌面端可用");
        }
        setBindBusyLabel(null);
        return;
      }
      const value = formatGrantReadonlyFolderAnswer(
        opt.label,
        result.root.name,
        result.namespace,
      );
      try {
        await onBindResolve(answer.composeWithAnswer("decision", q.id, value));
      } catch {
        setBindBusyLabel(null);
      }
      return;
    }

    if (opt.action === "grant_organize_folder") {
      const result = await pickAndGrantOrganizeFolder(conversationId);
      if (!result.ok) {
        if (result.reason === "error") setBindError(result.message);
        else if (result.reason === "unavailable") {
          setBindError("整理授权仅桌面端可用");
        }
        setBindBusyLabel(null);
        return;
      }
      const value = formatGrantOrganizeFolderAnswer(
        opt.label,
        result.root.name,
        result.namespace,
      );
      try {
        await onBindResolve(answer.composeWithAnswer("decision", q.id, value));
      } catch {
        setBindBusyLabel(null);
      }
      return;
    }

    const result = await pickAndBindLocalFolder(conversationId);
    if (!result.ok) {
      if (result.reason === "error") setBindError(result.message);
      setBindBusyLabel(null);
      return;
    }
    const value = formatBindLocalFolderAnswer(opt.label, result.root.name);
    try {
      await onBindResolve(answer.composeWithAnswer("decision", q.id, value));
    } catch {
      setBindBusyLabel(null);
    }
  };

  const questionRows = (q: AskQuestion): AskRow[] => {
    const picked = answer.answers[q.id] ?? [];
    const rows: AskRow[] = q.options.map((opt) => {
      const desktopFolder = isDesktopFolderAction(opt.action);
      const canRunFolder =
        desktopFolder &&
        (opt.action === "open_local_project" ? canLocalFs : canBindAction);
      const bindBusy = bindBusyLabel === opt.label;
      return {
        key: opt.label,
        label: opt.label,
        detail: opt.detail,
        hint: opt.recommended && q.default !== opt.label ? "推荐" : undefined,
        icon: desktopFolder ? (
          bindBusy ? (
            <Loader2 size={12} className="animate-spin" />
          ) : (
            <FolderOpen size={12} />
          )
        ) : undefined,
        selected: canRunFolder && (picked.includes(opt.label) || bindBusy),
        disabled: busy || (!!bindBusyLabel && !bindBusy),
        onSelect: () => {
          if (!desktopFolder) {
            answer.toggleChoice(q, opt.label);
            return;
          }
          // Web / 无本地文件：禁止退化成 toggleChoice（假确认）。
          if (!hasLocalFiles()) {
            setBindError(guideDesktopDownload());
            return;
          }
          if (canRunFolder) {
            void handleBindOption(q, opt);
            return;
          }
          setBindError(
            opt.action === "open_local_project"
              ? "打开本地项目仅桌面端可用"
              : "本机目录授权仅桌面端可用",
          );
        },
      };
    });
    rows.push({
      key: `${q.id}:__other__`,
      label: "其他…",
      icon: <Pencil size={12} />,
      muted: !answer.otherOn[q.id],
      selected: !!answer.otherOn[q.id],
      disabled: busy || !!bindBusyLabel,
      onSelect: () => answer.toggleOther(q),
    });
    return rows;
  };

  return (
    <AskCardShell
      variant="decision"
      icon={META.icon}
      caption={caption ?? META.activeCaption}
      title={content.question}
      subtitle={content.context || undefined}
      extra={<ManualHelpLink to={MANUAL_HELP.checkpoint} />}
      footer={
        <AskCardFooter
          cta={META.cta}
          ctaIcon={META.ctaIcon}
          busy={busy}
          submitting={submitting}
          onContinue={onContinue}
          onStop={onStop}
        />
      }
    >
      <div className="space-y-3">
        {content.assumptions.length > 0 && (
          <div className="space-y-1">
            <AskSectionLabel>起步计划</AskSectionLabel>
            <dl className="divide-y divide-border/60 px-2">
              {content.assumptions.map((a) => (
                <div key={a.id} className="flex gap-3 py-1.5">
                  <dt className="w-16 shrink-0 text-xs leading-snug text-muted-foreground">
                    {a.label}
                  </dt>
                  <dd className="min-w-0 flex-1 whitespace-pre-wrap text-xs leading-snug text-foreground/90">
                    {a.value}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        )}

        {content.questions.map((q) => (
          <div key={q.id}>
            <p className="px-2 text-xs font-medium leading-snug text-foreground">
              {q.prompt}
              {q.kind === "choice" && q.multiple && (
                <span className="ml-1.5 text-xs font-normal text-muted-foreground">
                  可多选
                </span>
              )}
            </p>
            {q.kind === "text" ? (
              <input
                type="text"
                value={(answer.answers[q.id] ?? [])[0] ?? ""}
                onChange={(e) => answer.setText(q, e.target.value)}
                disabled={busy}
                placeholder={q.default || "填写你的答案"}
                className="mt-2 w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/70 focus:border-foreground/25 focus:outline-none disabled:opacity-40"
              />
            ) : (
              <>
                <AskRowGroup
                  className="mt-1"
                  rows={questionRows(q)}
                  multiple={q.multiple}
                />
                {answer.otherOn[q.id] && (
                  <input
                    type="text"
                    value={answer.otherText[q.id] ?? ""}
                    onChange={(e) => answer.setOtherValue(q, e.target.value)}
                    disabled={busy}
                    // biome-ignore lint/a11y/noAutofocus: 用户点开「其他」才渲染此框，聚焦刚展开的字段是预期 UX。
                    autoFocus
                    placeholder="填写你的答案"
                    className="mt-1.5 w-full rounded-lg border border-border bg-card px-3 py-2 text-sm text-foreground placeholder:text-muted-foreground/70 focus:border-foreground/25 focus:outline-none disabled:opacity-40"
                  />
                )}
              </>
            )}
          </div>
        ))}

        {bindError && (
          <p className="px-2 text-xs text-destructive">{bindError}</p>
        )}

        {content.styleOptions.length > 0 && (
          <div className="space-y-1">
            <AskSectionLabel>风格基调</AskSectionLabel>
            <AskRowGroup
              rows={content.styleOptions.map((s) => ({
                key: s.id,
                label: s.label,
                selected: s.id === answer.styleId,
                disabled: busy,
                onSelect: () =>
                  answer.setStyleId(s.id === answer.styleId ? null : s.id),
              }))}
            />
          </div>
        )}

        {content.formatOptions.length > 0 && (
          <div className="space-y-1">
            <AskSectionLabel>交付形态</AskSectionLabel>
            <AskRowGroup
              rows={content.formatOptions.map((s) => ({
                key: s.id,
                label: s.label,
                selected: s.id === answer.formatId,
                disabled: busy,
                onSelect: () =>
                  answer.setFormatId(s.id === answer.formatId ? null : s.id),
              }))}
            />
          </div>
        )}

        <div className="px-2">
          <button
            type="button"
            onClick={() => setNoteOpen((v) => !v)}
            aria-expanded={noteOpen}
            className="flex w-full items-center gap-1.5 text-left"
          >
            <ChevronRight
              size={13}
              className={`shrink-0 text-muted-foreground transition-transform ${
                noteOpen ? "rotate-90" : ""
              }`}
            />
            <span className="shrink-0 text-xs text-muted-foreground">
              补充说明
            </span>
            {!noteOpen && answer.note.trim() && (
              <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground/70">
                {answer.note.trim()}
              </span>
            )}
          </button>
          {noteOpen && (
            <div className="mt-1.5 pl-5">
              <CommenceNote answer={answer} disabled={busy} compact />
            </div>
          )}
        </div>
      </div>
    </AskCardShell>
  );
}
