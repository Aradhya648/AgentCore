import type { PausedTurnSummary } from "@/api/turn";
// Durable resume card — the actionable surface for a turn that paused at a checkpoint then
// lost its live stream (结构化挂起 2b). Unlike PauseCard (which settles a LIVE fold
// `interactions[]` over the still-open SSE via resolveInteraction), this reads a
// PERSISTED PausedTurnSummary (no assistant message yet, only a frame) and asks the parent
// to drive a fresh resume stream (api/stream.ts::resumeStream).
//
// Mobile's own UI (cross-platform-frontend.mdc). ask_user 阻塞问答内核（choice/text/default
// chips）对齐 NonBlockingAskCard / 桌面 AskUserFields（P3 D4）.
import type { AskOption, CheckpointDecision } from "@agentcore/contract-types";
import { useState } from "react";

function str(record: Record<string, unknown>, key: string): string | null {
  const v = record[key];
  return typeof v === "string" && v.trim() ? v : null;
}

function asRecords(v: unknown): Array<Record<string, unknown>> {
  return Array.isArray(v)
    ? v.filter(
        (x): x is Record<string, unknown> =>
          !!x && typeof x === "object" && !Array.isArray(x),
      )
    : [];
}

/** Flatten ask_user option labels (bare string or `{label}`) for resume `selected`. */
function optionLabel(o: unknown): string {
  if (typeof o === "string") return o.trim();
  if (o && typeof o === "object" && !Array.isArray(o)) {
    return str(o as Record<string, unknown>, "label") ?? "";
  }
  return "";
}

/** Phase 3 最小对齐：有 model 才出「正方 X · 反方 Y · 裁判 Z」；无字段零噪声。 */
function vendorLabel(model: string | null | undefined): string | null {
  const m = (model ?? "").trim();
  if (!m) return null;
  const byPrefix: Record<string, string> = {
    doubao: "豆包",
    kimi: "Kimi",
    zhipu: "智谱",
    deepseek: "DeepSeek",
  };
  const prefix = m.includes("/") ? m.slice(0, m.indexOf("/")) : "";
  if (prefix) return byPrefix[prefix] ?? prefix;
  if (/^deepseek/i.test(m)) return "DeepSeek";
  if (/^doubao/i.test(m)) return "豆包";
  if (/^glm/i.test(m)) return "智谱";
  if (/^kimi/i.test(m)) return "Kimi";
  return m;
}

function formatDebateRosterLine(
  sides: Array<{ name?: string; model?: string; origin?: string }>,
  moderatorModel?: string | null,
  moderatorOrigin?: string | null,
): string | null {
  const hasAny =
    sides.some((s) => Boolean((s.model ?? "").trim())) ||
    Boolean((moderatorModel ?? "").trim());
  if (!hasAny) return null;
  const parts: string[] = [];
  for (const s of sides) {
    const label = vendorLabel(s.model);
    if (!label || !s.name) continue;
    parts.push(`${s.name} ${s.origin === "byok" ? `${label}·BYOK` : label}`);
  }
  const mod = vendorLabel(moderatorModel);
  if (mod) {
    parts.push(`裁判 ${moderatorOrigin === "byok" ? `${mod}·BYOK` : mod}`);
  }
  return parts.length > 0 ? parts.join(" · ") : null;
}

/** All choice option labels across questions — organize_plan confirm = keep-all. */
export function collectOrganizePlanSelected(
  questions: Array<Record<string, unknown>>,
): string[] {
  const out: string[] = [];
  for (const q of questions) {
    const options = Array.isArray(q.options) ? q.options : [];
    for (const o of options) {
      const label = optionLabel(o);
      if (label) out.push(label);
    }
  }
  return out;
}

const REVIEW_KIND_LABEL: Record<string, string> = {
  preference: "偏好",
  profile: "画像",
  topic: "主题",
  rule: "规则",
  doc: "文档",
};

function reviewOptionDetail(o: Record<string, unknown>): string | undefined {
  const kindRaw = str(o, "review_kind");
  const kind = kindRaw ? REVIEW_KIND_LABEL[kindRaw] : undefined;
  const summary = (str(o, "body") ?? str(o, "detail") ?? "").trim();
  if (kind && summary) return `${kind} · ${summary}`;
  if (kind) return kind;
  return summary || undefined;
}

/** Seed every choice label (mirrors desktop useAskAnswer seedAllMultiple). */
function seedAllMultipleAnswers(
  questions: Array<Record<string, unknown>>,
): Record<string, string[]> {
  const out: Record<string, string[]> = {};
  for (const q of questions) {
    const id = str(q, "id") ?? str(q, "prompt") ?? "";
    if (!id) continue;
    const options = Array.isArray(q.options) ? q.options : [];
    out[id] = options.map(optionLabel).filter(Boolean);
  }
  return out;
}

function pickedCount(answers: Record<string, string[]>): number {
  let n = 0;
  for (const labels of Object.values(answers)) n += labels.length;
  return n;
}

/** Intents whose continue settle carries `selected` (mirrors desktop CheckpointCard). */
const CARRIES_SELECTED = new Set([
  "proposal_pick",
  "risk_ack",
  "organize_plan",
  "daily_review",
]);

/** Intents with no per-item checkbox UI → confirm = keep all labels. */
const KEEP_ALL_ON_CONFIRM = new Set(["organize_plan"]);

/** Intents with row checkbox wall (default all on; uncheck = skip). */
const CHECKBOX_WALL = new Set(["daily_review"]);

export function ResumeCard({
  paused,
  onResume,
}: {
  paused: PausedTurnSummary;
  onResume: (
    decision: CheckpointDecision,
    note: string,
    selected: string[],
    styleId?: string | null,
    formatId?: string | null,
  ) => void;
}) {
  const [note, setNote] = useState("");
  const isPlanReview = paused.kind === "plan_review";
  const isTeamPreview = paused.kind === "team_preview";
  const isAskUser =
    paused.kind === "ask_user" || (!isPlanReview && !isTeamPreview);
  const showWorkers = isPlanReview || isTeamPreview;
  const questions = asRecords(paused.questions);
  const assumptions = asRecords(paused.assumptions);
  const styleOptions = asRecords(paused.style_options);
  const formatOptions = asRecords(paused.format_options);
  const intent = paused.intent ?? null;
  const isDailyReview = intent === "daily_review";
  // Per-question picks: proposal_pick / risk_ack chips; daily_review checkbox wall (seed all).
  const [answers, setAnswers] = useState<Record<string, string[]>>(() =>
    CHECKBOX_WALL.has(paused.intent ?? "")
      ? seedAllMultipleAnswers(asRecords(paused.questions))
      : {},
  );
  const [styleId, setStyleId] = useState<string | null>(() => {
    const first = styleOptions[0];
    return first ? (str(first, "id") ?? null) : null;
  });
  const [formatId, setFormatId] = useState<string | null>(() => {
    const first = formatOptions[0];
    return first ? (str(first, "id") ?? null) : null;
  });
  const isDebateKickoff =
    isTeamPreview && (paused as { primitive?: string }).primitive === "debate";
  const dailyPicked = isDailyReview ? pickedCount(answers) : 0;

  const pickChip = (
    questionId: string,
    prompt: string,
    value: string,
    multiple: boolean,
  ) => {
    const multi = questions.length > 1;
    const text = multi && prompt ? `${prompt}：${value}` : value;
    setNote((prev) => (prev.trim() ? `${prev}\n${text}` : text));
    if (
      !CARRIES_SELECTED.has(intent ?? "") ||
      KEEP_ALL_ON_CONFIRM.has(intent ?? "") ||
      CHECKBOX_WALL.has(intent ?? "")
    ) {
      return;
    }
    setAnswers((cur) => {
      const picked = cur[questionId] ?? [];
      if (multiple) {
        return {
          ...cur,
          [questionId]: picked.includes(value)
            ? picked.filter((o) => o !== value)
            : [...picked, value],
        };
      }
      return {
        ...cur,
        [questionId]: picked.includes(value) ? [] : [value],
      };
    });
  };

  const toggleCheck = (questionId: string, value: string) => {
    setAnswers((cur) => {
      const picked = cur[questionId] ?? [];
      return {
        ...cur,
        [questionId]: picked.includes(value)
          ? picked.filter((o) => o !== value)
          : [...picked, value],
      };
    });
  };

  const collectSelected = (decision: CheckpointDecision): string[] => {
    if (decision !== "continue" || !isAskUser) return [];
    let out: string[] = [];
    if (KEEP_ALL_ON_CONFIRM.has(intent ?? "")) {
      // organize_plan: no per-item checkbox UI → confirm = keep all.
      out = collectOrganizePlanSelected(questions);
    } else if (
      intent === "proposal_pick" ||
      intent === "risk_ack" ||
      CHECKBOX_WALL.has(intent ?? "")
    ) {
      for (const labels of Object.values(answers)) {
        for (const v of labels) {
          const t = v.trim();
          if (t) out.push(t);
        }
      }
    }
    // Structured style/format wire (B+A): append sN/fN when offered.
    if (styleId && !out.includes(styleId)) out = [...out, styleId];
    if (formatId && !out.includes(formatId)) out = [...out, formatId];
    return out;
  };

  const submit = (decision: CheckpointDecision) => {
    const stylePick =
      decision === "continue" && styleOptions.length > 0 ? styleId : null;
    const formatPick =
      decision === "continue" && formatOptions.length > 0 ? formatId : null;
    onResume(
      decision,
      note.trim(),
      collectSelected(decision),
      stylePick,
      formatPick,
    );
  };

  return (
    <div
      className="pause"
      data-ask-intent={isDailyReview ? "daily_review" : undefined}
    >
      <div className="pause-title">
        {isDebateKickoff
          ? "辩论开工 · 开赛前确认"
          : isTeamPreview
            ? "团队预审 · 开干前确认"
            : isPlanReview
              ? "执行已暂停 · 待你决定是否继续"
              : isDailyReview
                ? "复盘提案 · 确认要落盘的项"
                : "需要你拍板（已离线保留）"}
      </div>
      {paused.user_message && (
        <div className="pause-context">{paused.user_message}</div>
      )}
      {!showWorkers && paused.question && (
        <div className="pause-question">{paused.question}</div>
      )}
      {!showWorkers && paused.context && (
        <div className="pause-context">{paused.context}</div>
      )}
      {isAskUser && assumptions.length > 0 && (
        <div className="ask-assume">
          <div className="ask-assume-label">我先按这些默认推进</div>
          {assumptions.map((a) => (
            <div
              key={str(a, "id") ?? str(a, "label") ?? ""}
              className="ask-assume-row"
            >
              <span className="ask-assume-k">{str(a, "label")}</span>
              <span className="ask-assume-v">{str(a, "value")}</span>
            </div>
          ))}
        </div>
      )}
      {isAskUser &&
        questions.map((q) => {
          const id = str(q, "id") ?? str(q, "prompt") ?? "";
          const prompt = str(q, "prompt") ?? "";
          const kind = str(q, "kind");
          const def = str(q, "default");
          const multiple = Boolean(q.multiple);
          const options = asRecords(q.options);
          if (isDailyReview) {
            const picked = answers[id] ?? [];
            return (
              <div key={id} className="ask-question">
                {prompt && (
                  <div className="ask-prompt">
                    {prompt}
                    <span className="ask-prompt-hint">取消勾选即跳过</span>
                  </div>
                )}
                <fieldset className="ask-check-list">
                  {prompt ? (
                    <legend className="sr-only">{prompt}</legend>
                  ) : null}
                  {options.map((o) => {
                    const label = str(o, "label") ?? "";
                    if (!label) return null;
                    const detail = reviewOptionDetail(o);
                    const selected = picked.includes(label);
                    const inputId = `daily-review-${id}-${label}`;
                    return (
                      <label
                        key={label}
                        htmlFor={inputId}
                        className={
                          selected
                            ? "ask-check-row ask-check-row-active"
                            : "ask-check-row"
                        }
                      >
                        <input
                          id={inputId}
                          type="checkbox"
                          className="ask-check-input"
                          checked={selected}
                          onChange={() => toggleCheck(id, label)}
                        />
                        <span
                          className={
                            selected
                              ? "ask-check-box ask-check-box-on"
                              : "ask-check-box"
                          }
                          aria-hidden
                        />
                        <span className="ask-check-text">
                          <span className="ask-check-label">{label}</span>
                          {detail && (
                            <span className="ask-check-detail">{detail}</span>
                          )}
                        </span>
                      </label>
                    );
                  })}
                </fieldset>
              </div>
            );
          }
          const chips: AskOption[] =
            kind === "text"
              ? def
                ? [{ label: def }]
                : []
              : options
                  .map((o) => ({
                    label: str(o, "label") ?? "",
                    detail: str(o, "detail") ?? undefined,
                    recommended: Boolean(o.recommended),
                  }))
                  .filter((o) => o.label);
          return (
            <div key={id} className="ask-question">
              {prompt && <div className="ask-prompt">{prompt}</div>}
              {chips.length > 0 && (
                <div className="ask-chips">
                  {chips.map((opt) => {
                    const isDefault = !!def && opt.label === def;
                    return (
                      <button
                        key={opt.label}
                        type="button"
                        className="ask-chip"
                        onClick={() =>
                          pickChip(id, prompt, opt.label, multiple)
                        }
                      >
                        <span>{opt.label}</span>
                        {opt.recommended && (
                          <span className="ask-badge ask-badge-rec">推荐</span>
                        )}
                        {isDefault && <span className="ask-badge">默认</span>}
                      </button>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
      {isAskUser && styleOptions.length > 0 && (
        <div className="ask-chips">
          {styleOptions.map((s) => {
            const label = str(s, "label") ?? "";
            const id = str(s, "id") ?? label;
            const active = id === styleId;
            return (
              <button
                key={id}
                type="button"
                className={active ? "ask-chip ask-chip-active" : "ask-chip"}
                onClick={() => {
                  setStyleId(id);
                  setNote((prev) => {
                    const line = `风格：${label}`;
                    if (!prev.trim()) return line;
                    // Replace prior 风格 line if present; else append.
                    const lines = prev
                      .split("\n")
                      .filter((l) => !l.startsWith("风格："));
                    return [...lines, line].join("\n");
                  });
                }}
              >
                {label}
              </button>
            );
          })}
        </div>
      )}
      {isAskUser && formatOptions.length > 0 && (
        <div className="ask-chips">
          {formatOptions.map((s) => {
            const label = str(s, "label") ?? "";
            const id = str(s, "id") ?? label;
            const active = id === formatId;
            return (
              <button
                key={id}
                type="button"
                className={active ? "ask-chip ask-chip-active" : "ask-chip"}
                onClick={() => {
                  setFormatId(id);
                  setNote((prev) => {
                    const line = `形态：${label}`;
                    if (!prev.trim()) return line;
                    const lines = prev
                      .split("\n")
                      .filter((l) => !l.startsWith("形态："));
                    return [...lines, line].join("\n");
                  });
                }}
              >
                {label}
              </button>
            );
          })}
        </div>
      )}
      {isPlanReview && (paused.steps?.length ?? 0) > 0 && (
        <div className="pause-steps">
          {(paused.steps ?? []).map((s, i) => {
            const role = str(s, "role") ?? str(s, "task");
            const summary = str(s, "output_summary");
            return (
              // biome-ignore lint/suspicious/noArrayIndexKey: persisted, stable order
              <div key={i} className="pause-step">
                {role && <div className="pause-step-role">{role}</div>}
                {summary && <div className="pause-step-summary">{summary}</div>}
              </div>
            );
          })}
        </div>
      )}
      {isTeamPreview &&
        (paused as { primitive?: string }).primitive === "debate" && (
          <div className="pause-steps">
            {(paused as { motion?: string }).motion && (
              <div className="pause-step">
                <div className="pause-step-role">辩题</div>
                <div className="pause-step-summary">
                  {(paused as { motion: string }).motion}
                </div>
              </div>
            )}
            {(() => {
              const kick = paused as {
                sides?: Array<{
                  name?: string;
                  model?: string;
                  origin?: string;
                }>;
                moderator_model?: string;
                moderator_origin?: string;
              };
              const roster = formatDebateRosterLine(
                kick.sides ?? [],
                kick.moderator_model,
                kick.moderator_origin,
              );
              return roster ? (
                <div className="pause-step" data-testid="debate-roster-line">
                  <div className="pause-step-summary">{roster}</div>
                </div>
              ) : null;
            })()}
            {(
              (paused as { sides?: Array<Record<string, unknown>> }).sides ?? []
            ).map((s, i) => {
              const name = str(s, "name");
              const stance = str(s, "stance");
              return (
                // biome-ignore lint/suspicious/noArrayIndexKey: persisted, stable order
                <div key={i} className="pause-step">
                  {name && <div className="pause-step-role">{name}</div>}
                  {stance && <div className="pause-step-summary">{stance}</div>}
                </div>
              );
            })}
          </div>
        )}
      {isTeamPreview &&
        (paused as { primitive?: string }).primitive !== "debate" &&
        (paused.workers?.length ?? 0) > 0 && (
          <div className="pause-steps">
            {(paused.workers ?? []).map((w, i) => {
              const role = str(w, "role");
              const task = str(w, "task");
              return (
                // biome-ignore lint/suspicious/noArrayIndexKey: persisted, stable order
                <div key={i} className="pause-step">
                  {role && <div className="pause-step-role">{role}</div>}
                  {task && <div className="pause-step-summary">{task}</div>}
                </div>
              );
            })}
          </div>
        )}
      <textarea
        className="pause-note"
        rows={2}
        value={note}
        placeholder={
          isTeamPreview &&
          (paused as { primitive?: string }).primitive === "debate"
            ? "可选 · 开赛嘱咐（如你最关心的争议点），授权开赛时注入"
            : isTeamPreview
              ? "可选 · 对全体队员的嘱咐（授权开工时注入）"
              : isPlanReview
                ? "可选 · 调整时作为对下游的指示；停止时作为收尾备注"
                : "可选 · 你的答复或补充，留空则按上面继续"
        }
        onChange={(e) => setNote(e.target.value)}
      />
      <div className="pause-hint">
        {isDailyReview
          ? "确认后服务端直接写入记忆/规则/文档，无需再跑工具"
          : "等你拍板 · 不限时"}
      </div>
      <div className="pause-actions">
        <button
          type="button"
          className="pause-btn pause-btn-primary"
          disabled={isDailyReview && dailyPicked === 0}
          onClick={() => submit("continue")}
        >
          {isDebateKickoff
            ? "开赛"
            : isTeamPreview
              ? "授权并开工"
              : isDailyReview
                ? dailyPicked > 0
                  ? `确认落盘（${dailyPicked}）`
                  : "确认落盘"
                : "继续"}
        </button>
        {isPlanReview && (
          <button
            type="button"
            className="pause-btn pause-btn-neutral"
            disabled={!note.trim()}
            onClick={() => submit("adjust")}
          >
            调整
          </button>
        )}
        <button
          type="button"
          className="pause-btn pause-btn-danger"
          onClick={() => submit("stop")}
        >
          停止
        </button>
      </div>
    </div>
  );
}
