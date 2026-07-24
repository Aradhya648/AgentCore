// 委派授权卡 (delegation_authorization) — 手机自建，对齐桌面 DelegationAuthorizationCard。
import {
  type ResolveInteractionBody,
  resolveInteraction,
} from "@/api/interaction";
import {
  OrphanedInteractionCard,
  WaitingForDecisionHint,
} from "@/components/OrphanedInteractionCard";
import type { ProjectedInteraction } from "@agentcore/protocol-conformance";
import { useState } from "react";

type DelegationPending = Extract<
  ProjectedInteraction,
  { kind: "delegation_authorization" }
>;

const TOOL_LABELS: Record<string, string> = {
  file_write: "写入文件",
  file_append: "追加文件",
  str_replace: "修改文件",
  file_delete: "删除文件",
  file_move: "移动文件",
  code_execute: "执行代码",
};

export function DelegationAuthorizationCard({
  pending,
  conversationId,
  onResolved,
}: {
  pending: DelegationPending;
  conversationId: string;
  onResolved?: () => void;
}) {
  if (pending.status === "orphaned") {
    return (
      <OrphanedInteractionCard
        title="团队授权已失效"
        detail="该委派授权请求已不可答复（服务已重启或回合已结束）。"
      />
    );
  }
  if (pending.status !== "pending") return null;

  return (
    <DelegationBody
      pending={pending}
      conversationId={conversationId}
      onResolved={onResolved}
    />
  );
}

function DelegationBody({
  pending,
  conversationId,
  onResolved,
}: {
  pending: DelegationPending;
  conversationId: string;
  onResolved?: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  async function submit(decision: "grant_delegation" | "per_call" | "deny") {
    if (busy) return;
    setBusy(true);
    setErr(null);
    try {
      const body: ResolveInteractionBody = {
        kind: "delegation_authorization",
        decision,
      };
      await resolveInteraction(conversationId, pending.id, body);
      onResolved?.();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "授权失败");
      setBusy(false);
    }
  }

  const tools = pending.tools.map((t) => TOOL_LABELS[t] ?? t).join("、");
  const workers = pending.workers
    .map((w) => {
      const role = typeof w.role === "string" ? w.role : null;
      const task = typeof w.task === "string" ? w.task : null;
      return role ?? task;
    })
    .filter(Boolean)
    .join(" · ");

  return (
    <div className="pause">
      <div className="pause-title">团队开工前 · 工具授权</div>
      {workers && <div className="pause-context">{workers}</div>}
      {tools && <div className="pause-arg">涉及：{tools}</div>}
      <WaitingForDecisionHint />
      <div className="pause-actions">
        <button
          type="button"
          className="pause-btn pause-btn-primary"
          disabled={busy}
          onClick={() => void submit("grant_delegation")}
        >
          本轮都允许
        </button>
        <button
          type="button"
          className="pause-btn pause-btn-neutral"
          disabled={busy}
          onClick={() => void submit("per_call")}
        >
          逐次确认
        </button>
        <button
          type="button"
          className="pause-btn pause-btn-danger"
          disabled={busy}
          onClick={() => void submit("deny")}
        >
          拒绝
        </button>
      </div>
      {busy && <div className="pause-busy">处理中…</div>}
      {err && <div className="error pause-err">{err}</div>}
    </div>
  );
}
