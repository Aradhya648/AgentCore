import { Button, Textarea } from "@/components/ui";
import { surfaceSubtle } from "@/components/ui/tone-presets";
import { notifyError } from "@/lib/toast";
import { type DebateSteerDecision, submitDebateSteer } from "@/services/debate";
import type { Execution } from "@/stores/execution";
import {
  ArrowRight,
  Check,
  Hand,
  Loader2,
  MessageCircleQuestion,
  Plus,
} from "lucide-react";
import { useState } from "react";
import type { DebateModel } from "../model";
import { steeringAnchorId } from "./anchors";

export interface SentSteer {
  kind: "continue" | "conclude";
  ask: string;
  focus: string;
  targetName: string | null;
}

interface SteerTarget {
  key: string;
  name: string;
}

/** 掌舵面板：辩论流式区常驻输入；fire-and-forget，下一轮边界生效。 */
export function SteeringPanel({
  model,
  execution,
  conversationId,
  interactive,
}: {
  model: DebateModel;
  execution: Execution;
  conversationId: string | null;
  interactive: boolean;
}) {
  const [sent, setSent] = useState<SentSteer[]>([]);
  const live = interactive && !model.settled && !!conversationId;

  const targets: SteerTarget[] = (() => {
    const last = [...model.rounds].reverse().find((r) => r.sides.length > 0);
    // 同方多 beat（红队攻/复攻）按 sideKey 去重，掌舵定向不出现重复选项。
    const seen = new Set<string>();
    const out: SteerTarget[] = [];
    for (const s of last?.sides ?? []) {
      if (!s.sideKey || seen.has(s.sideKey)) continue;
      seen.add(s.sideKey);
      out.push({ key: s.sideKey, name: s.name });
    }
    return out;
  })();

  if (!live && sent.length === 0) return null;

  return (
    <div id={steeringAnchorId()} className="scroll-mt-28 space-y-3 py-4">
      {sent.map((s, i) => (
        <div
          key={`${s.kind}-${s.ask}-${s.focus}-${i}`}
          className="flex justify-end py-1 text-right text-sm"
        >
          <div>
            <p className="text-xs text-muted-foreground">
              你{s.targetName ? ` · 定向 ${s.targetName}` : ""}
              {s.kind === "conclude" ? " · 够了收" : ""}
              {s.focus ? ` · 角度「${s.focus}」` : ""}
              {" · 已发送·下一轮生效"}
            </p>
            {s.ask ? <p className="text-foreground">{s.ask}</p> : null}
          </div>
        </div>
      ))}
      {live && conversationId ? (
        <AmbientSteerBar
          conversationId={conversationId}
          executionId={execution.id}
          targets={targets}
          onSent={(item) => setSent((prev) => [...prev, item])}
        />
      ) : null}
    </div>
  );
}

function AmbientSteerBar({
  conversationId,
  executionId,
  targets,
  onSent,
}: {
  conversationId: string;
  executionId: string;
  targets: SteerTarget[];
  onSent: (item: SentSteer) => void;
}) {
  const [ask, setAsk] = useState("");
  const [angle, setAngle] = useState("");
  const [askTarget, setAskTarget] = useState("");
  const [showAngle, setShowAngle] = useState(false);
  const [submitting, setSubmitting] = useState<string | null>(null);
  const busy = submitting !== null;
  const hasAsk = ask.trim().length > 0;
  const hasAngle = angle.trim().length > 0;

  const send = (label: string, kind: "continue" | "conclude") => {
    if (busy) return;
    const trimmedAsk = ask.trim();
    const target = trimmedAsk ? askTarget : "";
    const focus = kind === "continue" ? angle.trim() : "";
    setSubmitting(label);
    const call: DebateSteerDecision =
      kind === "continue"
        ? { kind, focus, ask: trimmedAsk, askTarget: target }
        : { kind, ask: trimmedAsk, askTarget: target };
    submitDebateSteer(conversationId, {
      executionId,
      decision: call,
    })
      .then(() => {
        const targetName = target
          ? (targets.find((t) => t.key === target)?.name ?? null)
          : null;
        onSent({
          kind,
          ask: trimmedAsk,
          focus,
          targetName,
        });
        setAsk("");
        setAngle("");
        setAskTarget("");
        setShowAngle(false);
        setSubmitting(null);
      })
      .catch((err) => {
        notifyError(err, "提交失败");
        setSubmitting(null);
      });
  };

  const continueLabel = hasAsk
    ? "追问并继续"
    : hasAngle
      ? "按此角度继续"
      : "继续辩一轮";

  return (
    <div className={`rounded-xl border p-4 ${surfaceSubtle.primary}`}>
      <span className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
        <Hand size={14} className="text-muted-foreground" />
        随时掌舵 · 下一轮生效
      </span>
      <p className="mt-0.5 text-xs text-muted-foreground">
        辩论自动跑、不会因掌舵暂停。追问 / 加角度 / 够了收会在下一轮边界生效。
      </p>

      <Textarea
        value={ask}
        onChange={(e) => setAsk(e.target.value)}
        disabled={busy}
        rows={2}
        placeholder="追问辩手，让下一轮正面回答…（可选）"
        className="mt-2 w-full border-border bg-card/70 focus:border-primary/60"
      />
      {hasAsk && targets.length > 0 && (
        <div className="mt-1.5 flex flex-wrap items-center gap-1.5">
          <span className="inline-flex items-center gap-1 text-xs text-muted-foreground">
            <MessageCircleQuestion size={12} />
            追问对象
          </span>
          <SteerChip
            label="全场"
            active={askTarget === ""}
            disabled={busy}
            onClick={() => setAskTarget("")}
          />
          {targets.map((t) => (
            <SteerChip
              key={t.key}
              label={t.name}
              active={askTarget === t.key}
              disabled={busy}
              onClick={() => setAskTarget(t.key)}
            />
          ))}
        </div>
      )}
      {showAngle && (
        <Textarea
          value={angle}
          onChange={(e) => setAngle(e.target.value)}
          disabled={busy}
          rows={2}
          placeholder="下一轮想聚焦的角度…"
          className="mt-2 w-full border-border bg-card/70 focus:border-primary/60"
        />
      )}

      <div className="mt-2.5 flex flex-wrap items-center gap-1.5">
        <Button
          variant="primary"
          disabled={busy}
          onClick={() => send("continue", "continue")}
          icon={
            submitting === "continue" ? (
              <Loader2 size={13} className="animate-spin" />
            ) : hasAsk ? (
              <MessageCircleQuestion size={13} />
            ) : (
              <ArrowRight size={13} />
            )
          }
        >
          {continueLabel}
        </Button>
        <Button
          variant="neutral"
          disabled={busy}
          onClick={() => send("conclude", "conclude")}
          icon={
            submitting === "conclude" ? (
              <Loader2 size={13} className="animate-spin" />
            ) : (
              <Check size={13} />
            )
          }
        >
          够了，出结论
        </Button>
        {!showAngle && (
          <Button
            variant="ghost"
            disabled={busy}
            onClick={() => setShowAngle(true)}
            className="text-xs text-muted-foreground"
            icon={<Plus size={13} />}
          >
            加角度
          </Button>
        )}
      </div>
    </div>
  );
}

function SteerChip({
  label,
  active,
  disabled,
  onClick,
}: {
  label: string;
  active: boolean;
  disabled: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      disabled={disabled}
      onClick={onClick}
      aria-pressed={active}
      className={`rounded-full border px-2 py-0.5 text-xs font-medium transition-colors disabled:opacity-50 ${
        active
          ? "border-primary/60 bg-primary/10 text-primary"
          : "border-border text-muted-foreground hover:text-foreground"
      }`}
    >
      {label}
    </button>
  );
}
