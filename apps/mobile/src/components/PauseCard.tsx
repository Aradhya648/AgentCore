import {
  type ResolveInteractionBody,
  resolveInteraction,
} from "@/api/interaction";
// The interactive pause card — the actionable surface for a turn blocked on the user
// (前端技术与架构 §七 · 交互式暂停放行). The conformance-checked fold computes
// `interactions[]`; this turns an approval leaf into buttons that POST the decision to
// the live stream (api/interaction.ts), which resumes the SAME SSE.
//
// 挂起即收口 (②, Phase 3): only hot-path cards resolve live in-stream. A CEO checkpoint
// (ask_user) / plan_review / team_preview finalizes the turn and is continued via the
// durable ResumeCard (the single cold resume path).
//
// This is mobile's own UI (cross-platform-frontend.mdc: zero shared business components).
import { WaitingForDecisionHint } from "@/components/WaitingForDecisionHint";
import type { ApprovalDecision } from "@agentcore/contract-types";
import type { ProjectedInteraction } from "@agentcore/protocol-conformance";
import { type ReactNode, useState } from "react";

type ApprovalPending = Extract<ProjectedInteraction, { kind: "approval" }>;

/** Friendly zh labels for the GRANTABLE built-ins; falls back to the raw name. */
const TOOL_LABELS: Record<string, string> = {
  file_write: "写入文件",
  file_append: "追加文件",
  str_replace: "修改文件",
  file_delete: "删除文件",
  file_move: "移动文件",
  code_execute: "执行代码",
};

/** 本轮内所有文件改动 — 对齐后端 ``approval_class_tool_names()``
 * （文件改动五工具 ∪ {git}）。 */
export const FILE_OP_TOOLS: ReadonlySet<string> = new Set([
  "file_write",
  "file_append",
  "str_replace",
  "file_delete",
  "file_move",
  "git",
]);

/** Tools whose card omits「本轮都允许」— mirrors backend per_call_tool_names(). */
const PER_CALL_TOOLS: ReadonlySet<string> = new Set();

function primaryArg(args: Record<string, unknown>): string | null {
  for (const key of ["path", "file_path", "command", "code"]) {
    const v = args[key];
    if (typeof v === "string" && v.trim()) return v.trim();
  }
  return null;
}

export function PauseCard({
  pending,
  conversationId,
  onResolved,
}: {
  pending: ApprovalPending;
  conversationId: string;
  onResolved?: () => void;
}) {
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<string | null>(null);

  // Orphaned / non-pending: silent dismiss (no tombstone card).
  if (pending.status !== "pending") return null;

  async function submit(body: ResolveInteractionBody) {
    if (busy) return;
    setBusy(true);
    setErr(null);
    try {
      await resolveInteraction(conversationId, pending.id, body);
      onResolved?.();
    } catch (e) {
      setErr(e instanceof Error ? e.message : "放行失败");
      setBusy(false);
    }
  }

  return (
    <div className="pause">
      <ApprovalBody
        pending={pending}
        busy={busy}
        onDecide={(decision) => void submit({ kind: "approval", decision })}
      />
      <WaitingForDecisionHint />
      {busy && <div className="pause-busy">处理中…</div>}
      {err && <div className="error pause-err">{err}</div>}
    </div>
  );
}

function ApprovalBody({
  pending,
  busy,
  onDecide,
}: {
  pending: ApprovalPending;
  busy: boolean;
  onDecide: (decision: ApprovalDecision) => void;
}) {
  const headline = primaryArg(pending.arguments);
  const label = TOOL_LABELS[pending.toolName] ?? pending.toolName;
  return (
    <>
      <div className="pause-title">Agent 请求执行 · {label}</div>
      {headline && <div className="pause-arg">{headline}</div>}
      <div className="pause-actions">
        <Btn tone="primary" disabled={busy} onClick={() => onDecide("approve")}>
          允许一次
        </Btn>
        {!PER_CALL_TOOLS.has(pending.toolName) && (
          <Btn
            tone="neutral"
            disabled={busy}
            onClick={() => onDecide("approve_always")}
          >
            本轮都允许
          </Btn>
        )}
        {FILE_OP_TOOLS.has(pending.toolName) && (
          <Btn
            tone="neutral"
            disabled={busy}
            onClick={() => onDecide("approve_always_files")}
          >
            本轮内所有文件改动
          </Btn>
        )}
        <Btn tone="danger" disabled={busy} onClick={() => onDecide("deny")}>
          拒绝
        </Btn>
      </div>
    </>
  );
}

function Btn({
  tone,
  disabled,
  onClick,
  children,
}: {
  tone: "primary" | "neutral" | "danger";
  disabled: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      className={`pause-btn pause-btn-${tone}`}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  );
}
