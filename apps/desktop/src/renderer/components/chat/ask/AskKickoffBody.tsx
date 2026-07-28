/**
 * 生产 kickoff 开工提案卡 —— 单页全览 + 行式选项（{@link AskRowGroup}）。
 *
 * 与被它取代的 V2 Brief+Choose 的差别不在参数而在语言：选项从「一堆描边小方块」变成无边框行组，
 * 彩色「推荐 / 默认」徽章全删（`default` 由 {@link useAskAnswer} 预选，选中态即其表达），
 * 三个长得一样的灰色折叠入口收敛成一个（只剩「补充说明」）——起步计划改常驻两列表，brief 的
 * 要点直接进正文。字号拉出层级：标题 base、题干与选项 sm、辅助 xs。
 *
 * 答复模型不动：仍是 {@link useAskAnswer} + `compose()`，本文件纯视图层。
 * 由 {@link AskUserCard} 在 intent === "kickoff" 时挂载。
 */
import { MANUAL_HELP, ManualHelpLink } from "@/components/ManualHelpLink";
import { ASK_INTENT_META } from "@/components/chat/decision";
import {
  formatBindLocalFolderAnswer,
  pickAndBindLocalFolder,
} from "@/lib/bindLocalFolder";
import { hasLocalFiles } from "@/lib/capabilities";
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
import { CommenceNote, splitBriefContext } from "./AskCommenceParts";
import { type AskRow, AskRowGroup } from "./AskOptionRow";
import type { AskUserContent, useAskAnswer } from "./AskUserFields";

const META = ASK_INTENT_META.kickoff;

function isDesktopFolderAction(action: string | undefined): boolean {
  return (
    action === "open_local_project" ||
    action === "bind_local_folder" ||
    action === "grant_readonly_folder" ||
    action === "grant_organize_folder"
  );
}

export function AskKickoffBody({
  content,
  answer,
  busy,
  submitting,
  onContinue,
  onStop,
  conversationId,
  onBindResolve,
}: {
  content: AskUserContent;
  answer: ReturnType<typeof useAskAnswer>;
  busy: boolean;
  submitting: CheckpointUserDecision | null;
  onContinue: () => void;
  onStop: () => void;
  conversationId?: string | null;
  onBindResolve?: (composedAnswer: string) => void | Promise<void>;
}) {
  const navigate = useNavigate();
  const { lead, points } = splitBriefContext(content.context);
  const [bindBusyLabel, setBindBusyLabel] = useState<string | null>(null);
  const [bindError, setBindError] = useState<string | null>(null);
  const [noteOpen, setNoteOpen] = useState(false);

  const canLocalFs = hasLocalFiles() && !!window.fsApi;
  const canBindAction =
    !!conversationId && !!onBindResolve && canLocalFs;

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
        await onBindResolve(answer.composeWithAnswer("kickoff", q.id, value));
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
        await onBindResolve(answer.composeWithAnswer("kickoff", q.id, value));
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
      await onBindResolve(answer.composeWithAnswer("kickoff", q.id, value));
    } catch {
      setBindBusyLabel(null);
    }
  };

  /** 一题的行：选项 + 末行「其他…」。文件夹类选项换左侧图标并走 resolve / 打开项目路径。 */
  const questionRows = (q: AskQuestion): AskRow[] => {
    const picked = answer.answers[q.id] ?? [];
    const rows: AskRow[] = q.options.map((opt) => {
      const isFolderAction =
        isDesktopFolderAction(opt.action) &&
        (opt.action === "open_local_project" ? canLocalFs : canBindAction);
      const bindBusy = bindBusyLabel === opt.label;
      return {
        key: opt.label,
        label: opt.label,
        detail: opt.detail,
        // default 项靠选中态表达；只有推荐 ≠ 默认时才需要这句灰字。
        hint: opt.recommended && q.default !== opt.label ? "推荐" : undefined,
        icon: isFolderAction ? (
          bindBusy ? (
            <Loader2 size={12} className="animate-spin" />
          ) : (
            <FolderOpen size={12} />
          )
        ) : undefined,
        selected: picked.includes(opt.label) || bindBusy,
        disabled: busy || (!!bindBusyLabel && !bindBusy),
        onSelect: () =>
          isFolderAction
            ? void handleBindOption(q, opt)
            : answer.toggleChoice(q, opt.label),
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
      variant="kickoff"
      icon={META.icon}
      caption={META.activeCaption}
      title={content.question}
      subtitle={lead || undefined}
      extra={<ManualHelpLink to={MANUAL_HELP.checkpoint} />}
      footer={
        <AskCardFooter
          cta={META.cta}
          ctaIcon={META.ctaIcon}
          busy={busy}
          submitting={submitting}
          onContinue={onContinue}
          onStop={onStop}
          hint={
            answer.presetCount > 0
              ? `已预填 ${answer.presetCount} 项，直接开做或按需调整`
              : "也可直接在下方对话框回复"
          }
        />
      }
    >
      <div className="space-y-3">
        {points.length > 0 && (
          <ul className="space-y-1 px-2">
            {points.map((p) => (
              <li
                key={p}
                className="flex gap-2 text-xs leading-snug text-muted-foreground"
              >
                <span
                  className="mt-1.5 size-1 shrink-0 rounded-full bg-muted-foreground/50"
                  aria-hidden
                />
                <span>{p}</span>
              </li>
            ))}
          </ul>
        )}

        {content.assumptions.length > 0 && (
          <div className="space-y-1">
            <AskSectionLabel>起步计划</AskSectionLabel>
            {/* 只读参照物，密度刻意低于问题区——它不该把要作答的题挤出视口。 */}
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

        {/* 全卡唯一的折叠入口。 */}
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
