import { Button, Input, Textarea } from "@/components/ui";
import { bumpConversationCache } from "@/hooks/useConversations";
import {
  StreamError,
  describeStreamError,
  isRetriableStreamError,
  streamErrorAction,
} from "@/lib/errors";
import { cn } from "@/lib/utils";
import { resolveStageCardConversation } from "@/services/streamConversation";
import { finalizeGeneratingIfNeeded, isAbort } from "@/services/turns/helpers";
import { getRuntime, useConversationStore } from "@/stores/conversation";
import { beginTurnPreflight } from "@/stores/conversation/turnPhaseActions";
import {
  type InteractionEntry,
  useInteractionStore,
} from "@/stores/interactions";
/**
 * L3 推进卡 Pattern：阶段推进（建议开辩）可操作交互。
 * 独立于 DecisionCard（推进 ≠ 裁决）；壳用语义 Tailwind，控件用 L2。
 * 三键「按此开辩 / 先补充调研 / 调整命题」+ 可选开赛嘱咐；调整命题 = 改写后仍 start_debate。
 */
import { useState } from "react";

const FORM_LABEL: Record<string, string> = {
  debate: "正反辩论",
  red_team: "红队审查",
  roundtable: "圆桌讨论",
};

const shellClass =
  "rounded-xl border border-border bg-card p-3 text-sm text-foreground";

export function StageCard({ entry }: { entry: InteractionEntry }) {
  const p = entry.payload;
  const motion = String(p.motion ?? "");
  const form = String(p.form ?? "debate");
  const rationale = String(p.rationale ?? "");
  const thorough = p.thorough !== false;
  const maxRounds = Number(p.max_rounds ?? 5);
  const sides = Array.isArray(p.sides) ? p.sides : [];

  const [note, setNote] = useState("");
  const [editing, setEditing] = useState(false);
  const [motionDraft, setMotionDraft] = useState(motion);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (entry.status === "orphaned") {
    return (
      <div className={cn(shellClass, "opacity-70")} data-testid="stage-card">
        <div className="font-semibold">阶段推进卡已失效</div>
        <p className="mt-1 text-xs text-muted-foreground">
          你已继续对话，此开辩入口不再可用。
        </p>
      </div>
    );
  }
  if (entry.status === "resolved") {
    const decision = String(entry.resolution?.decision ?? "");
    return (
      <div className={cn(shellClass, "opacity-70")} data-testid="stage-card">
        <div className="font-semibold">
          {decision === "research_first" ? "已选择先补充调研" : "已按此开辩"}
        </div>
      </div>
    );
  }

  const conversationId = entry.conversationId;

  async function submit(
    decision: "start_debate" | "research_first",
    motionOverride?: string | null,
  ) {
    if (!conversationId || busy) return;
    if (getRuntime(conversationId).isGenerating) {
      setError("当前回合仍在生成中，请稍后再点");
      return;
    }
    setBusy(true);
    setError(null);
    const store = useConversationStore.getState();
    store.clearError(conversationId);
    bumpConversationCache(conversationId);
    store.createAssistantMessage(conversationId);
    const ac = new AbortController();
    store.setAbort(ac, conversationId);
    beginTurnPreflight(conversationId);
    try {
      await resolveStageCardConversation({
        conversationId,
        stageCardId: entry.id,
        decision,
        note,
        motionOverride: motionOverride ?? null,
        signal: ac.signal,
      });
      useInteractionStore.getState().markResolved({
        kind: "stage_card",
        id: entry.id,
        resolution: { decision, note, motion_override: motionOverride },
      });
    } catch (err) {
      if (err instanceof StreamError && err.status === 422) {
        // 检定失败：卡保持 pending + inline 错，仅清生成态（对齐 runSend）。
        const msg =
          (err as StreamError & { serverMessage?: string }).serverMessage ||
          "命题检定未通过，请改写后重试";
        setError(msg);
        finalizeGeneratingIfNeeded(conversationId);
        return;
      }
      // 非 422 / 用户中止：必须清 isGenerating，否则 composer 永久卡死。
      finalizeGeneratingIfNeeded(conversationId);
      if (isAbort(err)) return;
      const msg = describeStreamError(err);
      if (msg) {
        const retry = isRetriableStreamError(err)
          ? () => void submit(decision, motionOverride)
          : null;
        store.setError(msg, retry, conversationId, streamErrorAction(err));
      }
    } finally {
      setBusy(false);
      useConversationStore.getState().setAbort(null, conversationId);
    }
  }

  return (
    <div className={shellClass} data-testid="stage-card">
      <div className="mb-1.5 text-xs font-semibold tracking-wide text-muted-foreground">
        阶段推进 · 建议开辩
      </div>
      <div className="mb-2 font-semibold whitespace-pre-wrap">
        {editing ? (
          <Textarea
            className="w-full resize-y"
            value={motionDraft}
            onChange={(e) => setMotionDraft(e.target.value)}
            rows={2}
            disabled={busy}
          />
        ) : (
          <strong>{motion}</strong>
        )}
      </div>
      <ul className="mb-2 list-disc space-y-0.5 pl-4">
        {sides.map((s) => {
          const row = s as { key?: string; name?: string; stance?: string };
          return (
            <li key={String(row.key)}>
              <span className="mr-1.5 font-semibold">{row.name}</span>
              <span className="text-muted-foreground">{row.stance}</span>
            </li>
          );
        })}
      </ul>
      <div className="mb-2 text-xs text-muted-foreground">
        {FORM_LABEL[form] ?? form} · {thorough ? "认真辩透" : "快速对碰"} · 上限{" "}
        {maxRounds} 轮
      </div>
      {rationale ? (
        <p className="mb-2 text-xs text-muted-foreground">{rationale}</p>
      ) : null}
      <label
        className="mb-2 block text-xs text-muted-foreground"
        htmlFor="stage-debate-note"
      >
        <span>开赛嘱咐（可选）</span>
        <Input
          id="stage-debate-note"
          className="mt-1 w-full"
          type="text"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="例如：先盯证据缺口…"
          disabled={busy}
        />
      </label>
      {error ? <p className="mb-2 text-xs text-destructive">{error}</p> : null}
      <div className="flex flex-wrap gap-2">
        <Button
          variant="primary"
          disabled={busy}
          onClick={() =>
            void submit(
              "start_debate",
              editing ? motionDraft.trim() || null : null,
            )
          }
        >
          按此开辩
        </Button>
        <Button
          variant="neutral"
          className="border border-border"
          disabled={busy}
          onClick={() => void submit("research_first")}
        >
          先补充调研
        </Button>
        <Button
          variant="neutral"
          className="border border-border"
          disabled={busy}
          onClick={() => {
            setEditing((v) => !v);
            setMotionDraft(motion);
            setError(null);
          }}
        >
          {editing ? "取消调整" : "调整命题"}
        </Button>
      </div>
    </div>
  );
}
