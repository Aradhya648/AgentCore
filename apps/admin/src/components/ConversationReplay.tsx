import { CopyableId } from "@/components/CopyableId";
import { ChatTimeline } from "@/components/conversation-replay/ChatTimeline";
import { InspectorPanel } from "@/components/conversation-replay/InspectorPanel";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import { cn, fmtCny, fmtInt, fmtTime, nanoToYuan } from "@/lib/utils";
import {
  type AdminConversationReplay,
  type ReplayMessage,
  fetchConversationReplay,
} from "@/services/adminObservability";
import { errorMessage } from "@/services/api";
import { ArrowLeft, Users } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

export function ConversationReplay({
  conversationId,
  onBack,
  backLabel = "返回观测",
}: {
  conversationId: string;
  onBack: () => void;
  backLabel?: string;
}) {
  const [searchParams] = useSearchParams();
  const anchorTrace = searchParams.get("trace") ?? undefined;
  const anchorTurn = searchParams.get("turn") ?? undefined;

  const [data, setData] = useState<AdminConversationReplay | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedId, setSelectedId] = useState<string | null>(null);
  const [selectedRunId, setSelectedRunId] = useState<string | null>(null);
  /** Right dock only opens when a worker/node is selected — no standalone 检视入口. */
  const [dockOpen, setDockOpen] = useState(false);
  const didAnchor = useRef(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchConversationReplay(conversationId));
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [conversationId]);

  useEffect(() => {
    void load();
  }, [load]);

  const assistantTurns = useMemo(
    () => (data?.messages ?? []).filter((m) => m.role === "assistant"),
    [data],
  );

  const multiAgentTurns = useMemo(
    () => assistantTurns.filter((m) => m.runs.length > 0).length,
    [assistantTurns],
  );

  // Resolve URL anchor once data lands; scroll to turn only (do not open dock).
  useEffect(() => {
    if (!data || didAnchor.current) return;
    didAnchor.current = true;
    const byTurn = anchorTurn
      ? data.messages.find((m) => m.id === anchorTurn)
      : undefined;
    const byTrace = anchorTrace
      ? data.messages.find((m) => m.trace_id === anchorTrace)
      : undefined;
    const hit = byTurn ?? byTrace;
    if (hit) {
      setSelectedId(hit.id);
      return;
    }
    const first = assistantTurns[0];
    if (first) setSelectedId(first.id);
  }, [data, anchorTrace, anchorTurn, assistantTurns]);

  const selected =
    (data?.messages ?? []).find((m) => m.id === selectedId) ??
    assistantTurns[0] ??
    null;

  const selectTurn = useCallback((id: string) => {
    setSelectedId((prev) => {
      if (prev !== id) {
        setSelectedRunId(null);
        setDockOpen(false);
      }
      return id;
    });
  }, []);

  /** Click graph node → open worker dock. */
  const selectRun = useCallback((runId: string) => {
    setSelectedRunId(runId);
    setDockOpen(true);
  }, []);

  const clearRun = useCallback(() => {
    setSelectedRunId(null);
  }, []);

  const closeDock = useCallback(() => {
    setSelectedRunId(null);
    setDockOpen(false);
  }, []);

  const isAnchored = (m: ReplayMessage) =>
    (anchorTurn != null && m.id === anchorTurn) ||
    (anchorTrace != null && m.trace_id === anchorTrace);

  const dockCny =
    selected && selected.cost_total > 0 && data
      ? fmtCny(nanoToYuan(selected.cost_total))
      : null;

  return (
    <div className="mx-auto max-w-[1400px] px-4 py-5 sm:px-6 sm:py-6">
      <button
        type="button"
        onClick={onBack}
        className="mb-3 inline-flex items-center gap-1.5 text-muted-foreground text-sm outline-none transition-colors hover:text-foreground focus-visible:text-foreground"
      >
        <ArrowLeft size={16} />
        {backLabel}
      </button>

      {loading && (
        <div className="flex items-center justify-center gap-2 rounded-xl border border-border bg-card py-16 text-muted-foreground text-sm">
          <Spinner />
          加载中…
        </div>
      )}

      {!loading && error && (
        <div className="flex flex-col items-center gap-3 rounded-xl border border-border bg-card py-16 text-sm">
          <span className="text-destructive">{error}</span>
          <Button variant="outline" size="sm" onClick={() => void load()}>
            重试
          </Button>
        </div>
      )}

      {!loading && !error && data && (
        <div className="flex flex-col gap-3">
          <header className="rounded-xl border border-border bg-card px-4 py-3 sm:px-5">
            <div className="flex flex-wrap items-start justify-between gap-3">
              <div className="min-w-0 flex-1">
                <h1 className="truncate text-lg font-semibold text-foreground">
                  {data.conversation.title || "未命名会话"}
                </h1>
                <div className="mt-1 flex flex-wrap items-center gap-x-2 gap-y-1 text-muted-foreground text-xs">
                  <span>
                    {data.conversation.display_name ||
                      data.conversation.username ||
                      "未知用户"}
                    {data.conversation.username && (
                      <span> @{data.conversation.username}</span>
                    )}
                  </span>
                  <span aria-hidden>·</span>
                  <span className="tabular-nums">
                    {fmtTime(data.conversation.created_at)}
                  </span>
                  <span aria-hidden>·</span>
                  <CopyableId
                    value={data.conversation.id}
                    label="conversation_id"
                    display={data.conversation.id.slice(0, 8)}
                  />
                  {data.conversation.model_profile_name && (
                    <>
                      <span aria-hidden>·</span>
                      <span
                        title={
                          data.conversation.model_profile_id
                            ? `profile ${data.conversation.model_profile_id}`
                            : undefined
                        }
                      >
                        {data.conversation.model_profile_name}
                        {data.conversation.model_profile_id && (
                          <span className="ml-1 font-mono opacity-70">
                            {data.conversation.model_profile_id.slice(0, 8)}
                          </span>
                        )}
                      </span>
                    </>
                  )}
                </div>
              </div>
              <div className="flex flex-wrap items-center gap-1.5 text-xs">
                <KpiChip label="回合" value={fmtInt(data.turns)} />
                <KpiChip
                  label="错误"
                  value={fmtInt(data.errors)}
                  tone={data.errors > 0 ? "destructive" : undefined}
                />
                <KpiChip
                  label="成本"
                  value={fmtCny(
                    nanoToYuan(data.cost_total),
                  )}
                />
                {multiAgentTurns > 0 && (
                  <KpiChip
                    label="多 Agent"
                    value={`${multiAgentTurns} 回合`}
                    tone="primary"
                  />
                )}
              </div>
            </div>

            <TurnPills
              className="mt-3"
              turns={assistantTurns}
              selectedId={selected?.id ?? null}
              onSelect={selectTurn}
              anchorTrace={anchorTrace}
              anchorTurn={anchorTurn}
            />
          </header>

          {/* Narrow: timeline, or worker dock when a node is selected */}
          <div className="flex flex-col gap-3 lg:hidden">
            {dockOpen && selected ? (
              <InspectorPanel
                message={selected}
                selectedRunId={selectedRunId}
                onSelectRun={selectRun}
                onClearRun={clearRun}
                onClose={closeDock}
                cnyLabel={dockCny}
              />
            ) : (
              <ChatTimeline
                messages={data.messages}
                selectedId={selected?.id ?? null}
                selectedRunId={selectedRunId}
                onSelect={selectTurn}
                onSelectRun={selectRun}
                isAnchored={isAnchored}
              />
            )}
          </div>

          {/* Wide: chat main + contextual worker dock */}
          <div
            className={cn(
              "hidden lg:grid lg:gap-4",
              dockOpen
                ? "lg:grid-cols-[minmax(0,1fr)_480px]"
                : "lg:grid-cols-1",
            )}
          >
            <ChatTimeline
              messages={data.messages}
              selectedId={selected?.id ?? null}
              selectedRunId={selectedRunId}
              onSelect={selectTurn}
              onSelectRun={selectRun}
              isAnchored={isAnchored}
            />
            {dockOpen && selected && (
              <InspectorPanel
                message={selected}
                selectedRunId={selectedRunId}
                onSelectRun={selectRun}
                onClearRun={clearRun}
                onClose={closeDock}
                cnyLabel={dockCny}
              />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function KpiChip({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "destructive" | "primary";
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-md border border-border bg-muted/40 px-2 py-1 tabular-nums",
        tone === "destructive" && "border-destructive/30 text-destructive",
        tone === "primary" && "border-primary/30 text-primary",
      )}
    >
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium text-foreground">{value}</span>
    </span>
  );
}

function TurnPills({
  turns,
  selectedId,
  onSelect,
  anchorTrace,
  anchorTurn,
  className,
}: {
  turns: ReplayMessage[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  anchorTrace?: string;
  anchorTurn?: string;
  className?: string;
}) {
  if (turns.length === 0) {
    return (
      <p className={cn("text-muted-foreground text-xs", className)}>
        暂无助手回合
      </p>
    );
  }

  return (
    <div className={cn("flex flex-wrap items-center gap-1.5", className)}>
      <span className="mr-1 text-muted-foreground text-xs font-medium">
        回合
      </span>
      {turns.map((m, i) => {
        const isError = m.metrics?.status === "error";
        const multi = m.runs.length > 0 || m.metrics?.delegated;
        const anchored =
          (anchorTurn != null && m.id === anchorTurn) ||
          (anchorTrace != null && m.trace_id === anchorTrace);
        const active = selectedId === m.id;
        return (
          <button
            key={m.id}
            type="button"
            onClick={() => onSelect(m.id)}
            className={cn(
              "inline-flex items-center gap-1.5 rounded-lg border px-2.5 py-1 text-left text-xs outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
              active
                ? "border-primary/40 bg-primary/10 text-foreground"
                : "border-border bg-card text-muted-foreground hover:bg-muted/50 hover:text-foreground",
              anchored && !active && "ring-1 ring-primary/40",
            )}
          >
            <span className="font-medium tabular-nums">#{i + 1}</span>
            <span className="tabular-nums opacity-70">
              {fmtTime(m.created_at)}
            </span>
            {(isError || multi) && (
              <span className="flex items-center gap-1">
                {isError && <Badge tone="destructive">错</Badge>}
                {multi && (
                  <Badge tone="primary">
                    <Users size={10} className="mr-0.5" />
                    {m.metrics?.workers || m.runs.length || "多"}
                  </Badge>
                )}
              </span>
            )}
          </button>
        );
      })}
    </div>
  );
}
