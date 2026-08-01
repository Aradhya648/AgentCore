import { CopyableId } from "@/components/CopyableId";
import { ProcessTimeline } from "@/components/conversation-replay/ProcessTimeline";
import {
  CollapsibleBody,
  EmptyPanel,
  ROLE_LABEL,
  credentialSourceLabel,
} from "@/components/conversation-replay/shared";
import { Badge } from "@/components/ui/Badge";
import { cn, fmtCny, fmtMs, fmtTime, nanoToYuan } from "@/lib/utils";
import type { ReplayMessage } from "@/services/adminObservability";
import { Users } from "lucide-react";
import { useEffect, useRef } from "react";

export function ChatTimeline({
  messages,
  selectedId,
  selectedRunId,
  onSelect,
  onSelectRun,
  isAnchored,
}: {
  messages: ReplayMessage[];
  selectedId: string | null;
  selectedRunId: string | null;
  onSelect: (id: string) => void;
  onSelectRun: (runId: string) => void;
  isAnchored: (m: ReplayMessage) => boolean;
}) {
  const refs = useRef<Map<string, HTMLDivElement>>(new Map());

  useEffect(() => {
    if (!selectedId) return;
    const el = refs.current.get(selectedId);
    el?.scrollIntoView?.({
      behavior: "smooth",
      block: "nearest",
    });
  }, [selectedId]);

  return (
    <div className="flex max-h-[calc(100vh-11rem)] flex-col gap-4 overflow-y-auto pr-0.5">
      {messages.map((m) => (
        <div
          key={m.id}
          ref={(node) => {
            if (node) refs.current.set(m.id, node);
            else refs.current.delete(m.id);
          }}
        >
          {m.role === "user" ? (
            <UserBubble
              message={m}
              selected={m.id === selectedId}
              anchored={isAnchored(m)}
              onSelect={() => onSelect(m.id)}
            />
          ) : (
            <AssistantBubble
              message={m}
              selected={m.id === selectedId}
              selectedRunId={m.id === selectedId ? selectedRunId : null}
              anchored={isAnchored(m)}
              onSelect={() => onSelect(m.id)}
              onSelectRun={(runId) => {
                onSelect(m.id);
                onSelectRun(runId);
              }}
            />
          )}
        </div>
      ))}
      {messages.length === 0 && <EmptyPanel text="该会话暂无消息" />}
    </div>
  );
}

function UserBubble({
  message,
  selected,
  anchored,
  onSelect,
}: {
  message: ReplayMessage;
  selected: boolean;
  anchored: boolean;
  onSelect: () => void;
}) {
  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
      className={cn(
        "flex justify-end outline-none focus-visible:ring-2 focus-visible:ring-ring rounded-xl",
        selected && "ring-1 ring-primary/30",
        anchored && !selected && "ring-1 ring-primary/20",
      )}
    >
      <div
        className={cn(
          "max-w-[min(100%,36rem)] rounded-xl rounded-br-none border px-4 py-2.5",
          selected
            ? "border-primary/40 bg-primary/10"
            : "border-border/60 bg-muted/50",
        )}
      >
        <div className="mb-1 flex items-center gap-2 text-muted-foreground text-xs">
          <span className="font-medium text-foreground">
            {ROLE_LABEL.user}
          </span>
          <span className="tabular-nums">{fmtTime(message.created_at)}</span>
        </div>
        {message.content ? (
          <CollapsibleBody content={message.content} />
        ) : (
          <div className="text-muted-foreground text-sm italic">（无正文）</div>
        )}
      </div>
    </div>
  );
}

function AssistantBubble({
  message,
  selected,
  selectedRunId,
  anchored,
  onSelect,
  onSelectRun,
}: {
  message: ReplayMessage;
  selected: boolean;
  selectedRunId: string | null;
  anchored: boolean;
  onSelect: () => void;
  onSelectRun: (runId: string) => void;
}) {
  const metrics = message.metrics;
  const isError = metrics?.status === "error";
  const multi = message.runs.length > 0 || metrics?.delegated;
  const credLabel = credentialSourceLabel(message.credential_source);
  const models = message.models ?? [];

  return (
    <div
      role="button"
      tabIndex={0}
      onClick={onSelect}
      onKeyDown={(e) => {
        if (e.key === "Enter" || e.key === " ") {
          e.preventDefault();
          onSelect();
        }
      }}
      className={cn(
        "max-w-[min(100%,48rem)] rounded-xl px-1 py-1 outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
        selected && "ring-1 ring-primary/25",
        anchored && !selected && "ring-1 ring-primary/15",
      )}
    >
      <div className="mb-2 flex flex-wrap items-center gap-2">
        <span className="text-sm font-medium text-foreground">
          {ROLE_LABEL.assistant}
        </span>
        <span className="text-muted-foreground text-xs tabular-nums">
          {fmtTime(message.created_at)}
        </span>
        {multi && (
          <Badge tone="primary">
            <Users size={10} className="mr-0.5" />
            多 Agent
            {metrics?.workers ? ` · ${metrics.workers}` : ""}
          </Badge>
        )}
        {message.cost_total > 0 && (
          <span className="ml-auto text-muted-foreground text-xs tabular-nums">
            {fmtCny(nanoToYuan(message.cost_total))}
          </span>
        )}
      </div>

      <ProcessTimeline
        message={message}
        selectedRunId={selectedRunId}
        onSelectRun={onSelectRun}
      />

      {isError && metrics?.error && (
        <div className="mt-2 rounded-lg bg-destructive/10 px-3 py-2 text-destructive text-xs">
          {metrics.error}
        </div>
      )}

      {(models.length > 0 || credLabel) && (
        <div className="mt-2 flex flex-wrap items-center gap-1.5">
          {credLabel && <Badge tone="neutral">{credLabel}</Badge>}
          {models.map((m) => (
            <span
              key={m}
              className="rounded-lg border border-border bg-muted/40 px-1.5 py-0.5 font-mono text-xs text-muted-foreground"
            >
              {m}
            </span>
          ))}
        </div>
      )}

      {metrics && (
        <div className="mt-3 flex flex-wrap items-center gap-x-3 gap-y-1 border-border border-t pt-2 text-muted-foreground text-xs">
          <Badge tone={isError ? "destructive" : "success"}>
            {metrics.finish_reason ?? metrics.status}
          </Badge>
          <span className="tabular-nums">{metrics.rounds} 轮</span>
          <span className="tabular-nums">{fmtMs(metrics.duration_ms)}</span>
          {metrics.delegated && (
            <span className="tabular-nums">委派 {metrics.workers} 队员</span>
          )}
          {metrics.trace_id && (
            <CopyableId
              value={metrics.trace_id}
              label="trace_id"
              display={metrics.trace_id.slice(0, 8)}
              titleHint={`${metrics.trace_id}（点击复制 → log_timeline --trace / --pack）`}
            />
          )}
        </div>
      )}
    </div>
  );
}
