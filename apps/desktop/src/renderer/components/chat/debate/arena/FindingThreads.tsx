import { Markdown } from "@/components/chat/Markdown";
import { Button } from "@/components/ui";
import { statusAccentText } from "@/components/ui/tone-presets";
import type { Execution, RunNode } from "@/stores/execution";
import { useSidePanelStore } from "@/stores/sidePanel";
import { CornerDownRight, ShieldAlert } from "lucide-react";
import { SideIdentity } from "../SideChip";
import {
  FINDING_SEVERITY,
  FINDING_STATUS,
  findingDispositionLabel,
  sortFindings,
} from "../findings";
import type { DebateFindingView } from "../model";

/**
 * 红队英雄区：按 finding 线程渲染（刺 → 回应 → 复核），状态徽章驱动。
 * 对打感来自线程，不来自并排文章。全文靠 run_id 关联。
 */
export function FindingThreads({
  findings,
  execution,
  messageId,
}: {
  findings: DebateFindingView[];
  execution: Execution;
  messageId: string;
}) {
  if (findings.length === 0) return null;
  const ordered = sortFindings(findings);
  return (
    <div className="space-y-3 py-2">
      <h3 className="flex items-center gap-1.5 text-sm font-semibold text-foreground">
        <ShieldAlert size={15} className="text-muted-foreground" />
        Finding 台账
        <span className="text-xs font-normal text-muted-foreground">
          {ordered.length} 条
        </span>
      </h3>
      <ul className="space-y-3">
        {ordered.map((f) => (
          <FindingCard
            key={f.id}
            finding={f}
            execution={execution}
            messageId={messageId}
          />
        ))}
      </ul>
    </div>
  );
}

function FindingCard({
  finding: f,
  execution,
  messageId,
}: {
  finding: DebateFindingView;
  execution: Execution;
  messageId: string;
}) {
  const sev = FINDING_SEVERITY[f.severity];
  const st = FINDING_STATUS[f.status];
  const disposition = findingDispositionLabel(f.disposition);
  return (
    <li
      className={`rounded-lg border border-border bg-card/40 p-3 ${sev.surface}`}
    >
      <div className="flex flex-wrap items-center gap-1.5">
        <span className={sev.pill}>{sev.label}</span>
        <span className={st.pill}>{st.label}</span>
        {disposition && (
          <span className="text-xs text-muted-foreground">
            处置 · {disposition}
          </span>
        )}
        <span className="ml-auto font-mono text-xs text-muted-foreground">
          {f.id}
        </span>
      </div>
      <p className="mt-1.5 text-sm font-medium text-foreground">
        指向：{f.target || "（未标注部位）"}
      </p>
      <div className="mt-1 flex flex-wrap items-center gap-1.5">
        <span className="text-xs text-muted-foreground">攻击方</span>
        <SideIdentity name={f.attackerName} colorVar={f.attackerColorVar} />
        {f.mergedFrom.length > 0 && (
          <span className="text-xs text-muted-foreground">
            · 合并自 {f.mergedFrom.join("、")}
          </span>
        )}
      </div>
      <div className="mt-3 space-y-2">
        <BeatClip
          label="刺"
          run={f.attackRun}
          execution={execution}
          messageId={messageId}
          empty="攻击波尚未产出"
        />
        <BeatClip
          label="回应"
          run={f.responseRun}
          execution={execution}
          messageId={messageId}
          empty={beatEmpty(
            f.responseRun,
            f.status === "unanswered" || f.status === "open"
              ? "等待方案方逐条处置"
              : "暂无回应产出",
          )}
          indent
        />
        <BeatClip
          label="复核"
          run={f.rebuttalRun}
          execution={execution}
          messageId={messageId}
          empty={beatEmpty(
            f.rebuttalRun,
            f.status === "answered" || f.status === "open"
              ? "等待红队复攻"
              : "无复攻（快速档可无）",
          )}
          indent
        />
      </div>
    </li>
  );
}

function BeatClip({
  label,
  run,
  execution,
  messageId,
  empty,
  indent,
}: {
  label: string;
  run: RunNode | null;
  execution: Execution;
  messageId: string;
  empty: string;
  indent?: boolean;
}) {
  const showRunDetail = useSidePanelStore((s) => s.showRunDetail);
  const agent = run
    ? execution.agents.find((a) => a.id === run.agentId)
    : undefined;
  const text = agent ? agent.outputChunks.join("") : "";
  const streaming = run?.status === "running";
  const failed = run?.status === "failed";

  return (
    <div className={indent ? "border-l border-border pl-2.5" : undefined}>
      <div className="mb-0.5 flex items-center gap-1.5 text-xs text-muted-foreground">
        {indent && <CornerDownRight size={11} className="shrink-0" />}
        <span className="font-medium text-foreground">{label}</span>
        {streaming && (
          <span className={statusAccentText.primary}>正在输入…</span>
        )}
        {failed && <span className="text-destructive">失败</span>}
        {run && !streaming && (
          <Button
            variant="ghost"
            size="sm"
            className="ml-auto h-auto px-1 py-0 text-xs text-primary"
            onClick={() => showRunDetail(messageId, run.id, label)}
          >
            查看产出
          </Button>
        )}
      </div>
      {text ? (
        <div className="text-sm text-foreground">
          {streaming ? (
            <p className="whitespace-pre-wrap break-words">
              {text}
              <span
                className="ml-0.5 inline-block h-[1em] w-px animate-pulse bg-primary align-text-bottom"
                aria-hidden
              />
            </p>
          ) : (
            <Markdown content={clipText(text, 480)} />
          )}
        </div>
      ) : (
        <p className="text-xs text-muted-foreground">{empty}</p>
      )}
    </div>
  );
}

function clipText(text: string, max: number): string {
  const t = text.trim();
  if (t.length <= max) return t;
  return `${t.slice(0, max).trimEnd()}…`;
}

function beatEmpty(run: RunNode | null, waiting: string): string {
  if (!run) return waiting;
  if (run.status === "failed") return "本拍失败";
  if (run.status === "running") return "正在输入…";
  return "产出未挂到发言节点（旧磁带 / 金样缺 agent 时可见）";
}
