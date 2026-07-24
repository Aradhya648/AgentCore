import { bumpConversationCache } from "@/hooks/useConversations";
import {
  StreamError,
  describeStreamError,
  isRetriableStreamError,
  streamErrorAction,
} from "@/lib/errors";
import { resolveStageCardConversation } from "@/services/streamConversation";
import { finalizeGeneratingIfNeeded, isAbort } from "@/services/turns/helpers";
import { getRuntime, useConversationStore } from "@/stores/conversation";
import { beginTurnPreflight } from "@/stores/conversation/turnPhaseActions";
import {
  type InteractionEntry,
  useInteractionStore,
} from "@/stores/interactions";
/**
 * 阶段推进卡（批 B）：命题卡升级为可操作交互。
 * 三键「按此开辩 / 先补充调研 / 调整命题」+ 可选开赛嘱咐；调整命题 = 改写后仍 start_debate。
 */
import { useState } from "react";

const FORM_LABEL: Record<string, string> = {
  debate: "正反辩论",
  red_team: "红队审查",
  roundtable: "圆桌讨论",
};

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
      <div className="stage-card stage-card--orphaned" data-testid="stage-card">
        <div className="stage-card__title">阶段推进卡已失效</div>
        <p className="stage-card__hint">你已继续对话，此开辩入口不再可用。</p>
      </div>
    );
  }
  if (entry.status === "resolved") {
    const decision = String(entry.resolution?.decision ?? "");
    return (
      <div className="stage-card stage-card--resolved" data-testid="stage-card">
        <div className="stage-card__title">
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
    <div className="stage-card" data-testid="stage-card">
      <div className="stage-card__eyebrow">阶段推进 · 建议开辩</div>
      <div className="stage-card__motion">
        {editing ? (
          <textarea
            className="stage-card__motion-input"
            value={motionDraft}
            onChange={(e) => setMotionDraft(e.target.value)}
            rows={2}
            disabled={busy}
          />
        ) : (
          <strong>{motion}</strong>
        )}
      </div>
      <ul className="stage-card__sides">
        {sides.map((s) => {
          const row = s as { key?: string; name?: string; stance?: string };
          return (
            <li key={String(row.key)}>
              <span className="stage-card__side-name">{row.name}</span>
              <span className="stage-card__side-stance">{row.stance}</span>
            </li>
          );
        })}
      </ul>
      <div className="stage-card__meta">
        {FORM_LABEL[form] ?? form} · {thorough ? "认真辩透" : "快速对碰"} · 上限{" "}
        {maxRounds} 轮
      </div>
      {rationale ? <p className="stage-card__rationale">{rationale}</p> : null}
      <label className="stage-card__note">
        <span>开赛嘱咐（可选）</span>
        <input
          type="text"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          placeholder="例如：先盯证据缺口…"
          disabled={busy}
        />
      </label>
      {error ? <p className="stage-card__error">{error}</p> : null}
      <div className="stage-card__actions">
        <button
          type="button"
          className="stage-card__btn stage-card__btn--primary"
          disabled={busy}
          onClick={() =>
            void submit(
              "start_debate",
              editing ? motionDraft.trim() || null : null,
            )
          }
        >
          按此开辩
        </button>
        <button
          type="button"
          className="stage-card__btn"
          disabled={busy}
          onClick={() => void submit("research_first")}
        >
          先补充调研
        </button>
        <button
          type="button"
          className="stage-card__btn"
          disabled={busy}
          onClick={() => {
            setEditing((v) => !v);
            setMotionDraft(motion);
            setError(null);
          }}
        >
          {editing ? "取消调整" : "调整命题"}
        </button>
      </div>
    </div>
  );
}
