import {
  Badge,
  Button,
  DecisionCard,
  DecisionCardIcon,
  Textarea,
} from "@/components/ui";
import { SimpleTooltip } from "@/components/ui/tooltip";
import { notifyError } from "@/lib/toast";
import { cn } from "@/lib/utils";
import {
  submitInteraction,
  submitInteractionFeedback,
} from "@/services/interactionSubmit";
import type { PlanReviewUserDecision } from "@/services/planReview";
import { useConversationStore } from "@/stores/conversation";
import { usePersistentDisclosure } from "@/stores/disclosure";
import { useInteractionStore } from "@/stores/interactions";
import { type PendingResume, usePausedTurnStore } from "@/stores/pausedTurns";
import type { InteractionKind } from "@/types/interactionExt";
import {
  AlertTriangle,
  ArrowRight,
  Check,
  CheckCheck,
  ChevronDown,
  ChevronRight,
  GitBranch,
  Loader2,
  OctagonX,
  Pencil,
  Users,
} from "lucide-react";
import { type ComponentType, useRef, useState } from "react";
import { AskUserCard } from "./CheckpointCard";
import { formatCrossModelRosterLine } from "./debate/model";
import { TEAM_PRIMITIVE_META } from "./decision";

/** 结论超过此长度（或含换行）默认两行截断，可展开全文。 */
const CONCLUSION_CLAMP_CHARS = 60;

/** Cold-path pending cards only (`ask_user` / `plan_review` / `team_preview`). */
export function ResumePrompt() {
  const conversationId = useConversationStore((s) => s.currentConversationId);
  const pending = usePausedTurnStore((s) => s.pending);
  const byId = useInteractionStore((s) => s.byId);
  // Orphaned: silent dismiss (no tombstone card).
  const visible = pending.filter((p) => {
    if (p.conversationId !== conversationId) return false;
    return byId.get(p.checkpointId)?.status !== "orphaned";
  });
  if (visible.length === 0) return null;

  return (
    <div className="mx-4 mb-2 space-y-2">
      {visible.map((turn) => (
        <ResumeCard key={turn.messageId} turn={turn} />
      ))}
    </div>
  );
}

function ResumeCard({ turn }: { turn: PendingResume }) {
  // Cold-path Interaction kinds (`submitPath: "cold"` in INTERACTION_REGISTRY).
  const Card = COLD_RESUME_CARDS[turn.kind];
  return <Card turn={turn} />;
}

function coldKind(turn: PendingResume): InteractionKind {
  return turn.kind;
}

function useColdSubmit(turn: PendingResume) {
  const [submitting, setSubmitting] = useState<PlanReviewUserDecision | null>(
    null,
  );
  const entryStatus = useInteractionStore(
    (s) => s.byId.get(turn.checkpointId)?.status,
  );
  const busy = submitting !== null || entryStatus === "submitting";

  const send = (
    decision: PlanReviewUserDecision,
    selected: string[] = [],
    note = "",
  ) => {
    if (busy) return;
    setSubmitting(decision);
    void submitInteraction({
      id: turn.checkpointId,
      kind: coldKind(turn),
      conversationId: turn.conversationId,
      cold: {
        messageId: turn.messageId,
        decision,
        note,
        selected,
      },
    })
      .then((result) => {
        if (result !== "ok") {
          notifyError(submitInteractionFeedback(result));
          setSubmitting(null);
        }
      })
      .catch((err) => {
        notifyError(err, "提交失败");
        setSubmitting(null);
      });
  };

  return { submitting, busy, send };
}

/**
 * 上下文带（B1）：风险/建议与产出→下游同一行次要 meta，默认全收，点开再展开详情。
 * 结论仍在决策头；testid 保持兼容。
 */
function PlanReviewContextBand({
  turn,
  disclosureKey,
}: {
  turn: PendingResume;
  disclosureKey: string;
}) {
  const [ceoOpen, setCeoOpen] = usePersistentDisclosure(
    `${disclosureKey}:ceo-review`,
    false,
  );
  const [stepsOpen, setStepsOpen] = usePersistentDisclosure(
    `${disclosureKey}:steps`,
    false,
  );

  const review = turn.ceoReview;
  const riskCount = review?.risks.length ?? 0;
  const suggestionCount = review?.suggestions.length ?? 0;
  const hasCeo = riskCount > 0 || suggestionCount > 0;
  const hasSteps = turn.steps.length > 0;
  const hasPending = turn.pending.length > 0;
  if (!hasCeo && !hasSteps && !hasPending) return null;

  const ceoSummary = [
    riskCount > 0 ? `${riskCount} 风险` : null,
    suggestionCount > 0 ? `${suggestionCount} 建议` : null,
  ]
    .filter(Boolean)
    .join(" · ");

  const roles = turn.steps.map((s) => s.role).filter(Boolean);
  const stepsPreview =
    roles.length > 0 ? roles.join(" · ") : `${turn.steps.length} 步`;

  return (
    <div className="mt-2">
      <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs text-muted-foreground">
        {hasCeo && review && (
          <span data-testid="ceo-review-summary">
            <button
              type="button"
              onClick={() => setCeoOpen((v) => !v)}
              aria-expanded={ceoOpen}
              data-testid="ceo-review-more-toggle"
              className="inline-flex max-w-full cursor-pointer items-center gap-1 text-left hover:text-foreground"
            >
              <AlertTriangle
                size={13}
                className="shrink-0 text-foreground/70"
                aria-hidden
              />
              <span className="min-w-0 truncate font-medium text-foreground/80">
                {ceoSummary}
              </span>
              <ChevronRight
                size={13}
                className={cn(
                  "shrink-0 transition-transform",
                  ceoOpen && "rotate-90",
                )}
              />
            </button>
          </span>
        )}
        {hasSteps && (
          <button
            type="button"
            onClick={() => setStepsOpen((v) => !v)}
            aria-expanded={stepsOpen}
            data-testid="plan-review-steps-toggle"
            className="inline-flex max-w-full cursor-pointer items-center gap-1 text-left hover:text-foreground"
          >
            <ChevronRight
              size={13}
              className={cn(
                "shrink-0 transition-transform",
                stepsOpen && "rotate-90",
              )}
            />
            <span className="shrink-0 font-medium text-foreground/80">
              产出
            </span>
            {!stepsOpen && (
              <span className="min-w-0 truncate">· {stepsPreview}</span>
            )}
          </button>
        )}
        {hasPending && (
          <span className="inline-flex flex-wrap items-center gap-1.5">
            <ArrowRight size={13} className="shrink-0" />
            <span>下游</span>
            {turn.pending.map((n) => (
              <Badge key={n.run_id} tone="muted">
                {n.role}
              </Badge>
            ))}
          </span>
        )}
      </div>
      {ceoOpen && hasCeo && review && (
        <div className="mt-1.5 space-y-1 border-l-2 border-border/70 pl-2.5">
          <CeoReviewList label="风险" items={review.risks} />
          <CeoReviewList label="建议" items={review.suggestions} />
          <button
            type="button"
            onClick={() => setCeoOpen(false)}
            className="text-xs text-muted-foreground hover:text-foreground"
          >
            收起详情
          </button>
        </div>
      )}
      {stepsOpen && hasSteps && (
        <div className="mt-1.5 space-y-1.5 border-l-2 border-border/70 pl-2.5">
          {turn.steps.map((s) => (
            <div key={s.run_id}>
              <p className="text-xs font-medium text-foreground">{s.role}</p>
              {s.summary && (
                <p className="mt-0.5 whitespace-pre-wrap text-xs text-muted-foreground">
                  {s.summary}
                </p>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function CeoReviewList({ label, items }: { label: string; items: string[] }) {
  if (items.length === 0) return null;
  return (
    <div className="first:mt-0">
      <p className="text-xs font-medium text-foreground/80">{label}</p>
      <ul className="mt-0.5 space-y-0.5">
        {items.map((item) => (
          <li key={item} className="flex gap-1 text-xs text-muted-foreground">
            <span aria-hidden className="shrink-0">
              ·
            </span>
            <span className="min-w-0 whitespace-pre-wrap">{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ConclusionHero({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  const long = text.length > CONCLUSION_CLAMP_CHARS || text.includes("\n");
  return (
    <div className="mt-1">
      <p
        className={cn(
          "whitespace-pre-wrap text-sm leading-relaxed text-foreground/90",
          !open && long && "line-clamp-2",
        )}
      >
        {text}
      </p>
      {long && (
        <button
          type="button"
          onClick={() => setOpen((v) => !v)}
          className="mt-0.5 text-xs font-medium text-muted-foreground hover:text-foreground"
          data-testid="plan-review-conclusion-toggle"
        >
          {open ? "收起" : "展开全文"}
        </button>
      )}
    </div>
  );
}

function PlanReviewResumeCard({ turn }: { turn: PendingResume }) {
  const [note, setNote] = useState("");
  const noteRef = useRef<HTMLTextAreaElement>(null);
  const { submitting, busy, send } = useColdSubmit(turn);

  const spinnerOr = (
    decision: PlanReviewUserDecision,
    icon: React.ReactNode,
  ) =>
    submitting === decision ? (
      <Loader2 size={13} className="animate-spin" />
    ) : (
      icon
    );

  // 拍板中心（方案 C）：时间线只留单行标记，等谁 / 等什么 / 产出引用都在这张卡。
  const reviewedRoles = turn.steps.map((s) => s.role).filter(Boolean);
  const rolesLabel =
    reviewedRoles.length > 0 ? `「${reviewedRoles.join("、")}」` : "这一步";
  const disclosureKey = turn.checkpointId;
  const gateHint = turn.ceoReview?.source === "llm";

  const focusNote = () => {
    queueMicrotask(() => noteRef.current?.focus());
  };

  const continueBtn = (
    <Button
      variant="primary"
      icon={spinnerOr("continue", <Check size={13} />)}
      disabled={busy}
      onClick={() => send("continue", [], note.trim())}
      aria-label={gateHint ? "继续。继续后，把关要点将发给下游" : undefined}
    >
      继续
    </Button>
  );

  return (
    <DecisionCard
      tone="primary"
      animate
      className="mx-0 flex max-h-[min(60vh,36rem)] flex-col overflow-hidden p-0"
    >
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
          <div className="flex items-start gap-2">
            <DecisionCardIcon tone="primary">
              <GitBranch size={16} />
            </DecisionCardIcon>
            <div className="min-w-0 flex-1">
              <p className="text-xs font-medium text-primary">
                计划复核 · 等你确认
              </p>
              <p className="mt-0.5 text-sm font-semibold text-foreground">
                {rolesLabel}已完成
              </p>
              {turn.ceoReview?.conclusion && (
                <ConclusionHero text={turn.ceoReview.conclusion} />
              )}
              <PlanReviewContextBand
                turn={turn}
                disclosureKey={disclosureKey}
              />
            </div>
          </div>
        </div>

        <div className="shrink-0 space-y-2 border-t border-border bg-card/95 px-3 py-3 backdrop-blur-sm">
          <Textarea
            ref={noteRef}
            value={note}
            onChange={(e) => setNote(e.target.value)}
            disabled={busy}
            rows={2}
            placeholder="可选备注；调整时必填"
            className="w-full border-border bg-card/70 focus:border-primary/60"
            data-testid="plan-review-note"
          />
          <div className="flex flex-wrap items-center gap-1.5 pl-6">
            <Button
              variant="neutral"
              icon={spinnerOr("adjust", <Pencil size={13} />)}
              disabled={busy}
              onClick={() => {
                if (!note.trim()) {
                  focusNote();
                  return;
                }
                send("adjust", [], note.trim());
              }}
            >
              调整
            </Button>
            <Button
              variant="danger"
              icon={spinnerOr("stop", <OctagonX size={13} />)}
              disabled={busy}
              onClick={() => send("stop", [], note.trim())}
            >
              停止
            </Button>
            <span className="ml-auto" />
            {gateHint ? (
              <SimpleTooltip label="继续后，把关要点将发给下游">
                <span
                  className="inline-flex"
                  data-testid="plan-review-gate-notes-hint"
                >
                  {continueBtn}
                </span>
              </SimpleTooltip>
            ) : (
              continueBtn
            )}
          </div>
        </div>
      </div>
    </DecisionCard>
  );
}

function TeamPreviewWorkers({ turn }: { turn: PendingResume }) {
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(
    () => new Set(),
  );

  const toggle = (runId: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(runId)) next.delete(runId);
      else next.add(runId);
      return next;
    });
  };

  return (
    <div className="mt-2 space-y-1.5">
      {turn.workers.map((w) => {
        const open = expanded.has(w.run_id);
        const meta = (
          <div className="flex flex-wrap items-center gap-1.5">
            <p className="min-w-0 text-xs font-medium text-foreground">
              {w.role}
            </p>
            {w.write_capability_label && (
              <span
                className={
                  w.write_capability === "text_only"
                    ? "text-xs font-medium text-muted-foreground"
                    : "text-xs text-muted-foreground"
                }
              >
                {w.write_capability_label}
              </span>
            )}
            {w.debate && (
              <span className="text-xs text-muted-foreground">辩论</span>
            )}
            {w.depends_on.length > 0 && (
              <span className="text-xs text-muted-foreground">
                依赖 {w.depends_on.length} 步
              </span>
            )}
          </div>
        );

        if (!w.task) {
          return (
            <div
              key={w.run_id}
              className="rounded-lg border border-border bg-card/60 px-2.5 py-1.5"
            >
              {meta}
            </div>
          );
        }

        return (
          <div
            key={w.run_id}
            className="rounded-lg border border-border bg-card/60 px-2.5 py-1.5"
          >
            <button
              type="button"
              onClick={() => toggle(w.run_id)}
              aria-expanded={open}
              aria-label={open ? `收起 ${w.role} 任务` : `展开 ${w.role} 任务`}
              className="w-full text-left"
            >
              <div className="flex items-start gap-1.5">
                <div className="min-w-0 flex-1">{meta}</div>
                {open ? (
                  <ChevronDown
                    size={14}
                    className="mt-0.5 shrink-0 text-muted-foreground"
                  />
                ) : (
                  <ChevronRight
                    size={14}
                    className="mt-0.5 shrink-0 text-muted-foreground"
                  />
                )}
              </div>
              <p
                className={
                  open
                    ? "mt-0.5 whitespace-pre-wrap text-xs text-muted-foreground"
                    : "mt-0.5 line-clamp-1 text-xs text-muted-foreground"
                }
              >
                {w.task}
              </p>
            </button>
          </div>
        );
      })}
    </div>
  );
}

function TeamPreviewDebateBody({ turn }: { turn: PendingResume }) {
  const [expanded, setExpanded] = useState<ReadonlySet<string>>(
    () => new Set(),
  );

  const toggle = (key: string) => {
    setExpanded((prev) => {
      const next = new Set(prev);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  const rosterLine = formatCrossModelRosterLine(turn.sides, {
    model: turn.moderatorModel,
    origin: turn.moderatorOrigin,
  });

  return (
    <div className="mt-2 space-y-1.5">
      {turn.motion && (
        <p className="whitespace-pre-wrap text-sm text-foreground">
          {turn.motion}
        </p>
      )}
      {rosterLine && (
        <p
          className="text-xs text-muted-foreground"
          data-testid="debate-roster-line"
        >
          {rosterLine}
        </p>
      )}
      {turn.sameModelDebate && (
        <p className="text-xs text-muted-foreground">同模型辩论</p>
      )}
      {turn.modelCandidates && turn.modelCandidates.length > 0 && (
        <div
          className="rounded-lg border border-border bg-card/60 px-2.5 py-1.5"
          data-testid="debate-model-candidates"
        >
          <p className="text-xs font-medium text-foreground">
            模型消歧失败 · 请从目录候选重选（勿再问「是不是当前主模型」）
          </p>
          <ul className="mt-1 space-y-0.5">
            {turn.modelCandidates.map((c, i) => (
              <li
                key={`${c.origin}-${c.model}-${c.provider_id ?? ""}-${i}`}
                className="text-xs text-muted-foreground"
              >
                {c.label || c.model}
                {" · "}
                {c.origin}/{c.model}
                {c.provider_id ? `（provider=${c.provider_id}）` : ""}
                {c.side_key ? ` · ${c.side_key}` : ""}
              </li>
            ))}
          </ul>
        </div>
      )}
      {turn.sides.map((s) => {
        const open = expanded.has(s.key);
        const meta = (
          <div className="flex flex-wrap items-center gap-1.5">
            <p className="min-w-0 text-xs font-medium text-foreground">
              {s.name}
            </p>
            {s.is_subject && (
              <span className="text-xs text-muted-foreground">方案方</span>
            )}
          </div>
        );

        if (!s.stance) {
          return (
            <div
              key={s.key}
              className="rounded-lg border border-border bg-card/60 px-2.5 py-1.5"
            >
              {meta}
            </div>
          );
        }

        return (
          <div
            key={s.key}
            className="rounded-lg border border-border bg-card/60 px-2.5 py-1.5"
          >
            <button
              type="button"
              onClick={() => toggle(s.key)}
              aria-expanded={open}
              aria-label={open ? `收起 ${s.name} 立场` : `展开 ${s.name} 立场`}
              className="w-full text-left"
            >
              <div className="flex items-start gap-1.5">
                <div className="min-w-0 flex-1">{meta}</div>
                {open ? (
                  <ChevronDown
                    size={14}
                    className="mt-0.5 shrink-0 text-muted-foreground"
                  />
                ) : (
                  <ChevronRight
                    size={14}
                    className="mt-0.5 shrink-0 text-muted-foreground"
                  />
                )}
              </div>
              <p
                className={
                  open
                    ? "mt-0.5 whitespace-pre-wrap text-xs text-muted-foreground"
                    : "mt-0.5 line-clamp-1 text-xs text-muted-foreground"
                }
              >
                {s.stance}
              </p>
            </button>
          </div>
        );
      })}
    </div>
  );
}

function TeamPreviewResumeCard({ turn }: { turn: PendingResume }) {
  const [note, setNote] = useState("");
  const [capsOpen, setCapsOpen] = useState(false);
  const { submitting, busy, send } = useColdSubmit(turn);
  const isDebate = turn.primitive === "debate";
  const family = TEAM_PRIMITIVE_META[isDebate ? "debate" : "delegate"];
  const showCapabilities = !isDebate && turn.tools.length > 0;
  const debateBudget = isDebate
    ? turn.maxRounds > 0
      ? turn.thorough
        ? `认真辩透 · ${turn.maxRounds} 轮`
        : `快速对碰 · ${turn.maxRounds} 轮`
      : turn.thorough
        ? "认真辩透"
        : "快速对碰"
    : null;

  const spinnerOr = (
    decision: PlanReviewUserDecision,
    icon: React.ReactNode,
  ) =>
    submitting === decision ? (
      <Loader2 size={13} className="animate-spin" />
    ) : (
      icon
    );

  const toolLabel = (name: string) =>
    (
      ({
        file_write: "写入文件",
        file_append: "追加文件",
        str_replace: "修改文件",
        file_delete: "删除文件",
        file_move: "移动文件",
        file_copy: "复制文件",
        mkdir: "创建目录",
        file_batch: "批量文件操作",
        code_execute: "执行代码",
        test_run: "运行测试",
        git: "Git 写入",
      }) as Record<string, string>
    )[name] ?? name;

  const capPreview = turn.tools.slice(0, 2).map(toolLabel);
  const capRest = turn.tools.length - capPreview.length;

  return (
    <DecisionCard
      tone="primary"
      animate
      className="mx-0 flex max-h-[min(60vh,36rem)] flex-col overflow-hidden p-0"
    >
      <div className="flex min-h-0 flex-1 flex-col overflow-hidden">
        <div className="min-h-0 flex-1 overflow-y-auto px-3 py-3">
          <div className="flex items-start gap-2">
            <DecisionCardIcon tone="primary">
              <Users size={16} />
            </DecisionCardIcon>
            <div className="min-w-0 flex-1">
              <div className="flex items-center justify-between gap-2">
                <p className="text-xs font-medium text-primary">
                  {family.activeCaption}
                </p>
                {debateBudget && (
                  <Badge tone="muted" className="font-normal">
                    {debateBudget}
                  </Badge>
                )}
              </div>
              <p className="mt-1 text-sm text-foreground">
                {family.resumeLead}
              </p>
              {isDebate ? (
                <TeamPreviewDebateBody turn={turn} />
              ) : (
                <TeamPreviewWorkers turn={turn} />
              )}

              {showCapabilities && (
                <div className="mt-2">
                  <p className="mb-1 text-xs text-muted-foreground">
                    可逆写入已由「本会话信任」放行；以下为执行类。
                  </p>
                  <button
                    type="button"
                    onClick={() => setCapsOpen((v) => !v)}
                    aria-expanded={capsOpen}
                    className="flex w-full items-center gap-1.5 text-left"
                  >
                    <ChevronRight
                      size={13}
                      className={`shrink-0 text-muted-foreground transition-transform ${
                        capsOpen ? "rotate-90" : ""
                      }`}
                    />
                    <span className="shrink-0 text-xs font-medium text-foreground">
                      将授权的执行能力
                    </span>
                    {!capsOpen && (
                      <span className="min-w-0 flex-1 truncate text-xs text-muted-foreground">
                        {capPreview.join(" · ")}
                        {capRest > 0 ? ` · +${capRest}` : ""}
                      </span>
                    )}
                    {!capsOpen && capRest > 0 && (
                      <span className="shrink-0 rounded-full bg-muted px-1.5 py-0.5 text-xs text-muted-foreground">
                        +{capRest}
                      </span>
                    )}
                  </button>
                  {capsOpen && (
                    <div className="mt-1 flex flex-wrap gap-1 pl-5">
                      {turn.tools.map((tool) => (
                        <Badge key={tool} tone="muted" className="font-normal">
                          {toolLabel(tool)}
                        </Badge>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          </div>
        </div>

        <div className="shrink-0 space-y-2 border-t border-border bg-card/95 px-3 py-3 backdrop-blur-sm">
          <Textarea
            value={note}
            onChange={(e) => setNote(e.target.value)}
            disabled={busy}
            rows={2}
            placeholder={family.notePlaceholder}
            className="w-full border-border bg-card/70 focus:border-primary/60"
          />
          <div className="flex flex-wrap items-center gap-1.5 pl-6">
            <Button
              variant="primary"
              icon={spinnerOr("continue", <CheckCheck size={13} />)}
              disabled={busy}
              onClick={() => send("continue", [], note.trim())}
            >
              {isDebate
                ? family.resumeCta
                : showCapabilities
                  ? family.resumeCta
                  : "开做"}
            </Button>
            <Button
              variant="danger"
              icon={spinnerOr("stop", <OctagonX size={13} />)}
              disabled={busy}
              onClick={() => send("stop", [], note.trim())}
            >
              停止
            </Button>
          </div>
        </div>
      </div>
    </DecisionCard>
  );
}

function AskUserResumeCard({ turn }: { turn: PendingResume }) {
  return (
    <AskUserCard
      content={turn}
      intent={turn.intent}
      disclosureKey={turn.checkpointId}
      conversationId={turn.conversationId}
      onSubmit={async (decision, note, selected = []) => {
        const result = await submitInteraction({
          id: turn.checkpointId,
          kind: "ask_user",
          conversationId: turn.conversationId,
          cold: {
            messageId: turn.messageId,
            decision: decision as PlanReviewUserDecision,
            note,
            selected,
          },
        });
        if (result !== "ok") {
          throw new Error(submitInteractionFeedback(result));
        }
      }}
    />
  );
}

/** Cold-path resume cards — keyed by registry `submitPath: "cold"` kinds. */
const COLD_RESUME_CARDS: Record<
  "ask_user" | "plan_review" | "team_preview",
  ComponentType<{ turn: PendingResume }>
> = {
  ask_user: AskUserResumeCard,
  plan_review: PlanReviewResumeCard,
  team_preview: TeamPreviewResumeCard,
};
