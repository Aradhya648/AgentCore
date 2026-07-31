import { CopyableId } from "@/components/CopyableId";
import { Markdown } from "@/components/Markdown";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import { cn, fmtCny, fmtInt, fmtMs, fmtTime, nanoUsdToCny } from "@/lib/utils";
import {
  type AdminConversationReplay,
  type ReplayMessage,
  type ReplayRun,
  type ReplaySpan,
  fetchConversationReplay,
} from "@/services/adminObservability";
import { errorMessage } from "@/services/api";
import { ArrowLeft, ChevronRight, Users } from "lucide-react";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useSearchParams } from "react-router-dom";

const ROLE_LABEL: Record<string, string> = {
  user: "用户",
  assistant: "助手",
  system: "系统",
};

type ReplayTab = "timeline" | "team" | "turns";

const STATUS_TONE: Record<
  string,
  "neutral" | "primary" | "success" | "warning" | "destructive"
> = {
  pending: "neutral",
  running: "primary",
  completed: "success",
  failed: "destructive",
  cancelled: "warning",
  skipped: "neutral",
};

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
  const [tab, setTab] = useState<ReplayTab>("timeline");
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

  // Resolve URL anchor once data lands; otherwise pick first assistant turn.
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
      if (hit.role === "assistant") setTab("team");
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
      if (prev !== id) setSelectedRunId(null);
      return id;
    });
  }, []);

  const selectRun = useCallback(
    (runId: string, opts?: { focusTeam?: boolean }) => {
      setSelectedRunId(runId);
      if (opts?.focusTeam) setTab("team");
    },
    [],
  );

  const isAnchored = (m: ReplayMessage) =>
    (anchorTurn != null && m.id === anchorTurn) ||
    (anchorTrace != null && m.trace_id === anchorTrace);

  return (
    <div className="mx-auto max-w-[1400px] px-4 py-6 sm:px-6 sm:py-8">
      <button
        type="button"
        onClick={onBack}
        className="mb-4 inline-flex items-center gap-1.5 text-muted-foreground text-sm outline-none transition-colors hover:text-foreground focus-visible:text-foreground"
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
        <div className="flex flex-col gap-4">
          <header className="rounded-xl border border-border bg-card p-5">
            <h1 className="text-xl font-semibold text-foreground">
              {data.conversation.title || "未命名会话"}
            </h1>
            <p className="mt-1 text-muted-foreground text-sm">
              {data.conversation.display_name ||
                data.conversation.username ||
                "未知用户"}
              {data.conversation.username && (
                <span className="text-muted-foreground">
                  {" "}
                  @{data.conversation.username}
                </span>
              )}
              {" · "}
              {fmtTime(data.conversation.created_at)}
            </p>
            <div className="mt-4 flex flex-wrap items-center gap-6 text-sm">
              <Meta label="回合" value={fmtInt(data.turns)} />
              <Meta
                label="错误"
                value={fmtInt(data.errors)}
                tone={data.errors > 0 ? "destructive" : undefined}
              />
              <Meta
                label="成本"
                value={fmtCny(nanoUsdToCny(data.cost_total, data.cny_per_usd))}
              />
              {assistantTurns.some((m) => m.runs.length > 0) && (
                <Meta
                  label="多 Agent"
                  value={`${assistantTurns.filter((m) => m.runs.length > 0).length} 回合`}
                />
              )}
            </div>
            <CopyableId
              className="mt-3 block"
              value={data.conversation.id}
              label="conversation_id"
            />
          </header>

          {/* Narrow: tabs */}
          <div className="flex flex-col gap-3 lg:hidden">
            <div className="inline-flex items-center self-start rounded-lg border border-border p-0.5">
              {(
                [
                  { id: "timeline", label: "时间线" },
                  { id: "team", label: "协作" },
                  { id: "turns", label: "回合" },
                ] as const
              ).map((it) => (
                <button
                  key={it.id}
                  type="button"
                  aria-pressed={tab === it.id}
                  onClick={() => setTab(it.id)}
                  className={cn(
                    "h-7 rounded-lg px-3 text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
                    tab === it.id
                      ? "bg-accent text-accent-foreground"
                      : "text-muted-foreground hover:text-foreground",
                  )}
                >
                  {it.label}
                </button>
              ))}
            </div>
            {tab === "turns" && (
              <TurnDirectory
                turns={assistantTurns}
                selectedId={selected?.id ?? null}
                onSelect={(id) => {
                  selectTurn(id);
                  setTab("timeline");
                }}
                anchorTrace={anchorTrace}
                anchorTurn={anchorTurn}
              />
            )}
            {tab === "timeline" && (
              <TimelineColumn
                messages={data.messages}
                cnyPerUsd={data.cny_per_usd}
                selectedId={selected?.id ?? null}
                selectedRunId={selectedRunId}
                onSelect={selectTurn}
                onSelectRun={(runId) => selectRun(runId, { focusTeam: true })}
                isAnchored={isAnchored}
              />
            )}
            {tab === "team" && selected && (
              <TeamColumn
                message={selected}
                selectedRunId={selectedRunId}
                onSelectRun={selectRun}
              />
            )}
            {tab === "team" && !selected && (
              <EmptyPanel text="选择一个助手回合查看协作树" />
            )}
          </div>

          {/* Wide: 左回合 | 中时间线 | 右协作 */}
          <div className="hidden gap-4 lg:grid lg:grid-cols-[220px_minmax(0,1fr)_320px]">
            <TurnDirectory
              turns={assistantTurns}
              selectedId={selected?.id ?? null}
              onSelect={selectTurn}
              anchorTrace={anchorTrace}
              anchorTurn={anchorTurn}
            />
            <TimelineColumn
              messages={data.messages}
              cnyPerUsd={data.cny_per_usd}
              selectedId={selected?.id ?? null}
              selectedRunId={selectedRunId}
              onSelect={selectTurn}
              onSelectRun={selectRun}
              isAnchored={isAnchored}
            />
            {selected ? (
              <TeamColumn
                message={selected}
                selectedRunId={selectedRunId}
                onSelectRun={selectRun}
              />
            ) : (
              <EmptyPanel text="选择一个助手回合查看协作树" />
            )}
          </div>
        </div>
      )}
    </div>
  );
}

function Meta({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone?: "destructive";
}) {
  return (
    <div>
      <div className="text-muted-foreground text-xs">{label}</div>
      <div
        className={`mt-0.5 font-medium tabular-nums ${tone === "destructive" ? "text-destructive" : "text-foreground"}`}
      >
        {value}
      </div>
    </div>
  );
}

function EmptyPanel({ text }: { text: string }) {
  return (
    <div className="rounded-xl border border-border bg-card py-10 text-center text-muted-foreground text-sm">
      {text}
    </div>
  );
}

function TurnDirectory({
  turns,
  selectedId,
  onSelect,
  anchorTrace,
  anchorTurn,
}: {
  turns: ReplayMessage[];
  selectedId: string | null;
  onSelect: (id: string) => void;
  anchorTrace?: string;
  anchorTurn?: string;
}) {
  return (
    <aside className="flex max-h-[70vh] flex-col overflow-hidden rounded-xl border border-border bg-card">
      <div className="border-border border-b px-3 py-2 text-muted-foreground text-xs font-medium">
        回合目录 · {turns.length}
      </div>
      <ol className="flex-1 overflow-y-auto p-2">
        {turns.map((m, i) => {
          const isError = m.metrics?.status === "error";
          const multi = m.runs.length > 0 || m.metrics?.delegated;
          const anchored =
            (anchorTurn != null && m.id === anchorTurn) ||
            (anchorTrace != null && m.trace_id === anchorTrace);
          return (
            <li key={m.id}>
              <button
                type="button"
                onClick={() => onSelect(m.id)}
                className={cn(
                  "mb-1 w-full rounded-lg px-2.5 py-2 text-left outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
                  selectedId === m.id
                    ? "bg-accent text-accent-foreground"
                    : "hover:bg-muted/60",
                  anchored && selectedId !== m.id && "ring-1 ring-primary/40",
                )}
              >
                <div className="flex items-center justify-between gap-2">
                  <span className="text-xs font-medium">#{i + 1}</span>
                  <span className="text-[11px] text-muted-foreground tabular-nums">
                    {fmtTime(m.created_at)}
                  </span>
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-1">
                  <Badge tone={isError ? "destructive" : "success"}>
                    {m.metrics?.finish_reason ?? m.metrics?.status ?? "—"}
                  </Badge>
                  {multi && (
                    <Badge tone="primary">
                      <Users size={10} className="mr-0.5" />
                      {m.metrics?.workers || m.runs.length || "多"}
                    </Badge>
                  )}
                </div>
              </button>
            </li>
          );
        })}
        {turns.length === 0 && (
          <li className="px-2 py-6 text-center text-muted-foreground text-xs">
            暂无助手回合
          </li>
        )}
      </ol>
    </aside>
  );
}

function TimelineColumn({
  messages,
  cnyPerUsd,
  selectedId,
  selectedRunId,
  onSelect,
  onSelectRun,
  isAnchored,
}: {
  messages: ReplayMessage[];
  cnyPerUsd: number;
  selectedId: string | null;
  selectedRunId: string | null;
  onSelect: (id: string) => void;
  onSelectRun: (runId: string) => void;
  isAnchored: (m: ReplayMessage) => boolean;
}) {
  const refs = useRef<Map<string, HTMLDivElement>>(new Map());
  const runRefs = useRef<Map<string, HTMLElement>>(new Map());

  useEffect(() => {
    if (!selectedId) return;
    const el = refs.current.get(selectedId);
    el?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [selectedId]);

  useEffect(() => {
    if (!selectedRunId) return;
    const el = runRefs.current.get(selectedRunId);
    el?.scrollIntoView({ behavior: "smooth", block: "nearest" });
  }, [selectedRunId]);

  return (
    <div className="flex max-h-[70vh] flex-col gap-3 overflow-y-auto">
      {messages.map((m) => (
        <div
          key={m.id}
          ref={(node) => {
            if (node) refs.current.set(m.id, node);
            else refs.current.delete(m.id);
          }}
        >
          <MessageBlock
            message={m}
            cnyPerUsd={cnyPerUsd}
            selected={m.id === selectedId}
            selectedRunId={m.id === selectedId ? selectedRunId : null}
            anchored={isAnchored(m)}
            onSelect={() => onSelect(m.id)}
            onSelectRun={(runId) => {
              onSelect(m.id);
              onSelectRun(runId);
            }}
            runRef={(runId, node) => {
              if (node) runRefs.current.set(runId, node);
              else runRefs.current.delete(runId);
            }}
          />
        </div>
      ))}
      {messages.length === 0 && <EmptyPanel text="该会话暂无消息" />}
    </div>
  );
}

function TeamColumn({
  message,
  selectedRunId,
  onSelectRun,
}: {
  message: ReplayMessage;
  selectedRunId: string | null;
  onSelectRun: (runId: string) => void;
}) {
  const runs = message.runs;
  const spans = message.spans;
  return (
    <aside className="flex max-h-[70vh] flex-col gap-3 overflow-y-auto">
      <div className="rounded-xl border border-border bg-card p-3">
        <div className="mb-2 text-muted-foreground text-xs font-medium">
          协作树
        </div>
        {runs.length === 0 ? (
          <p className="text-muted-foreground text-xs">
            本回合无多 Agent 委派
          </p>
        ) : (
          <RunTree
            runs={runs}
            selectedRunId={selectedRunId}
            onSelectRun={onSelectRun}
          />
        )}
      </div>
      {spans.length > 0 && (
        <div className="rounded-xl border border-border bg-card p-3">
          <div className="mb-2 text-muted-foreground text-xs font-medium">
            执行明细 · 按 run
          </div>
          <SpansByRun
            spans={spans}
            runs={runs}
            selectedRunId={selectedRunId}
            onSelectRun={onSelectRun}
          />
        </div>
      )}
    </aside>
  );
}

function RunTree({
  runs,
  selectedRunId,
  onSelectRun,
}: {
  runs: ReplayRun[];
  selectedRunId: string | null;
  onSelectRun: (runId: string) => void;
}) {
  const byParent = useMemo(() => {
    const map = new Map<string | null, ReplayRun[]>();
    for (const r of runs) {
      const key = r.parent_run_id ?? null;
      const list = map.get(key) ?? [];
      list.push(r);
      map.set(key, list);
    }
    return map;
  }, [runs]);

  const roots = byParent.get(null) ?? [];
  // Orphans whose parent is missing from the list still render at top level.
  const known = new Set(runs.map((r) => r.run_id));
  const orphans = runs.filter(
    (r) => r.parent_run_id != null && !known.has(r.parent_run_id),
  );
  const top = roots.length > 0 ? roots : orphans.length > 0 ? orphans : runs;
  const nodeRefs = useRef<Map<string, HTMLElement>>(new Map());

  useEffect(() => {
    if (!selectedRunId) return;
    nodeRefs.current.get(selectedRunId)?.scrollIntoView({
      behavior: "smooth",
      block: "nearest",
    });
  }, [selectedRunId]);

  const renderNode = (run: ReplayRun, depth: number) => {
    const children = byParent.get(run.run_id) ?? [];
    const active = selectedRunId === run.run_id;
    return (
      <li key={run.run_id} className="mb-1">
        <button
          type="button"
          ref={(node) => {
            if (node) nodeRefs.current.set(run.run_id, node);
            else nodeRefs.current.delete(run.run_id);
          }}
          onClick={() => onSelectRun(run.run_id)}
          className={cn(
            "w-full rounded-lg border px-2 py-1.5 text-left outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
            active
              ? "border-primary/50 bg-primary/10 ring-1 ring-primary/30"
              : "border-border/60 bg-muted/30 hover:bg-muted/50",
          )}
          style={{ marginLeft: depth * 12 }}
        >
          <div className="flex flex-wrap items-center gap-1.5">
            <Badge tone={STATUS_TONE[run.status] ?? "neutral"}>
              {run.status}
            </Badge>
            <span className="text-foreground text-xs font-medium">
              {run.role || run.agent_id}
            </span>
            {run.kind !== "agent" && (
              <span className="text-muted-foreground text-[10px]">
                {run.kind}
              </span>
            )}
          </div>
          {run.task && (
            <p className="mt-0.5 text-muted-foreground text-[11px] line-clamp-2">
              {run.task}
            </p>
          )}
          {run.output_summary && (
            <p className="mt-0.5 text-foreground text-[11px] line-clamp-2">
              {run.output_summary}
            </p>
          )}
          {run.error && (
            <p className="mt-0.5 text-destructive text-[11px]">{run.error}</p>
          )}
        </button>
        {children.length > 0 && (
          <ul className="mt-1">{children.map((c) => renderNode(c, depth + 1))}</ul>
        )}
      </li>
    );
  };

  return <ul>{top.map((r) => renderNode(r, 0))}</ul>;
}

function SpansByRun({
  spans,
  runs,
  selectedRunId,
  onSelectRun,
}: {
  spans: ReplaySpan[];
  runs: ReplayRun[];
  selectedRunId: string | null;
  onSelectRun: (runId: string) => void;
}) {
  const runLabel = useMemo(() => {
    const m = new Map<string, string>();
    for (const r of runs) {
      m.set(r.run_id, r.role || r.agent_id || r.run_id.slice(0, 8));
    }
    return m;
  }, [runs]);

  const groups = useMemo(() => {
    const order: (string | null)[] = [];
    const map = new Map<string | null, ReplaySpan[]>();
    for (const s of spans) {
      const key = s.run_id ?? null;
      if (!map.has(key)) {
        map.set(key, []);
        order.push(key);
      }
      map.get(key)!.push(s);
    }
    return order.map((k) => ({ runId: k, spans: map.get(k)! }));
  }, [spans]);

  return (
    <div className="flex flex-col gap-2">
      {groups.map(({ runId, spans: group }) => {
        const active = runId != null && selectedRunId === runId;
        return (
          <div
            key={runId ?? "_none"}
            className={cn(
              "rounded-lg p-1.5 transition-colors",
              active && "bg-primary/10 ring-1 ring-primary/30",
            )}
          >
            <button
              type="button"
              disabled={!runId}
              onClick={() => runId && onSelectRun(runId)}
              className={cn(
                "mb-1 text-left text-[11px] font-medium text-muted-foreground outline-none",
                runId && "hover:text-foreground focus-visible:text-foreground",
              )}
            >
              {runId
                ? (runLabel.get(runId) ?? runId.slice(0, 8))
                : "未归属"}
              <span className="ml-1 font-normal">· {group.length}</span>
            </button>
            <ol className="flex flex-col gap-1.5 border-border border-l pl-2">
              {group.map((s, i) => (
                <SpanRow key={`${runId}-${i}`} span={s} />
              ))}
            </ol>
          </div>
        );
      })}
    </div>
  );
}

function MessageBlock({
  message,
  cnyPerUsd,
  selected,
  selectedRunId,
  anchored,
  onSelect,
  onSelectRun,
  runRef,
}: {
  message: ReplayMessage;
  cnyPerUsd: number;
  selected: boolean;
  selectedRunId: string | null;
  anchored: boolean;
  onSelect: () => void;
  onSelectRun: (runId: string) => void;
  runRef: (runId: string, node: HTMLElement | null) => void;
}) {
  const metrics = message.metrics;
  const isError = metrics?.status === "error";
  const multi = message.runs.length > 0 || metrics?.delegated;
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
        "rounded-xl border bg-card p-4 outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
        selected ? "border-primary/50 ring-1 ring-primary/30" : "border-border",
        anchored && !selected && "border-primary/40 bg-primary/5",
      )}
    >
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <Badge tone={message.role === "assistant" ? "primary" : "neutral"}>
            {ROLE_LABEL[message.role] ?? message.role}
          </Badge>
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
        </div>
        {message.cost_total > 0 && (
          <span className="text-muted-foreground text-xs tabular-nums">
            {fmtCny(nanoUsdToCny(message.cost_total, cnyPerUsd))}
          </span>
        )}
      </div>

      {message.content ? (
        <Markdown content={message.content} />
      ) : (
        <div className="text-muted-foreground text-sm italic">（无正文）</div>
      )}

      {message.runs
        .filter((r) => r.content)
        .map((r) => {
          const active = selectedRunId === r.run_id;
          return (
            <div
              key={r.run_id}
              ref={(node) => runRef(r.run_id, node)}
              role="button"
              tabIndex={0}
              onClick={(e) => {
                e.stopPropagation();
                onSelectRun(r.run_id);
              }}
              onKeyDown={(e) => {
                if (e.key === "Enter" || e.key === " ") {
                  e.preventDefault();
                  e.stopPropagation();
                  onSelectRun(r.run_id);
                }
              }}
              className={cn(
                "mt-3 cursor-pointer rounded-lg border px-3 py-2 outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
                active
                  ? "border-primary/50 bg-primary/10 ring-1 ring-primary/30"
                  : "border-border/70 bg-muted/40 hover:bg-muted/60",
              )}
            >
              <div className="mb-1 flex flex-wrap items-center gap-2">
                <Badge tone="primary">{r.role || r.agent_id}</Badge>
                {r.task && (
                  <span className="text-muted-foreground text-xs">{r.task}</span>
                )}
                {r.output_summary && (
                  <span className="text-foreground text-xs">
                    {r.output_summary}
                  </span>
                )}
              </div>
              <Markdown content={r.content!} />
              {r.debrief && typeof r.debrief === "object" && (
                <DebriefBlock debrief={r.debrief as Record<string, unknown>} />
              )}
            </div>
          );
        })}

      {isError && metrics?.error && (
        <div className="mt-2 rounded-lg bg-destructive/10 px-3 py-2 text-destructive text-xs">
          {metrics.error}
        </div>
      )}

      {metrics && (
        <div className="mt-3 flex flex-wrap items-center gap-x-4 gap-y-1 border-border border-t pt-2 text-muted-foreground text-xs">
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

      {message.spans.length > 0 && message.runs.length === 0 && (
        <SpanList spans={message.spans} />
      )}
    </div>
  );
}

function DebriefBlock({ debrief }: { debrief: Record<string, unknown> }) {
  const summary = typeof debrief.summary === "string" ? debrief.summary : null;
  const points = Array.isArray(debrief.key_points)
    ? debrief.key_points.filter((p): p is string => typeof p === "string")
    : [];
  if (!summary && points.length === 0) return null;
  return (
    <div className="mt-2 border-border border-t pt-2 text-xs text-muted-foreground">
      {summary && <p className="text-foreground">{summary}</p>}
      {points.length > 0 && (
        <ul className="mt-1 list-disc pl-4">
          {points.map((p) => (
            <li key={p}>{p}</li>
          ))}
        </ul>
      )}
    </div>
  );
}

function SpanList({ spans }: { spans: ReplaySpan[] }) {
  const [open, setOpen] = useState(false);
  const tools = spans.filter((s) => s.kind === "tool").length;
  const llms = spans.length - tools;
  return (
    <div className="mt-2">
      <button
        type="button"
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        className="inline-flex items-center gap-1 text-muted-foreground text-xs outline-none transition-colors hover:text-foreground focus-visible:text-foreground"
      >
        <ChevronRight
          size={13}
          className={cn("transition-transform", open && "rotate-90")}
        />
        执行明细 {spans.length} 步（LLM {llms} · 工具 {tools}）
      </button>
      {open && (
        <ol className="mt-2 flex flex-col gap-1.5 border-border border-l pl-3">
          {spans.map((s, i) => (
            <SpanRow key={i} span={s} />
          ))}
        </ol>
      )}
    </div>
  );
}

function SpanRow({ span }: { span: ReplaySpan }) {
  if (span.kind === "tool") {
    return (
      <li className="text-xs">
        <div className="flex items-center gap-2">
          <Badge tone={span.success === false ? "destructive" : "neutral"}>
            工具
          </Badge>
          <span className="font-medium text-foreground">{span.name ?? "—"}</span>
          <span
            className={
              span.success === false ? "text-destructive" : "text-success"
            }
          >
            {span.success === false ? "失败" : "成功"}
          </span>
        </div>
        {span.args_preview && (
          <pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-words rounded bg-muted px-2 py-1 font-mono text-[11px] text-muted-foreground">
            {span.args_preview}
          </pre>
        )}
        {span.result_preview && (
          <pre className="mt-1 overflow-x-auto whitespace-pre-wrap break-words rounded bg-muted/60 px-2 py-1 font-mono text-[11px] text-muted-foreground">
            → {span.result_preview}
          </pre>
        )}
      </li>
    );
  }
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
      <Badge tone="primary">LLM</Badge>
      {span.round_idx != null && (
        <span className="text-muted-foreground tabular-nums">
          第 {span.round_idx + 1} 轮
        </span>
      )}
      {span.finish_reason && (
        <span className="text-muted-foreground">{span.finish_reason}</span>
      )}
      <span className="text-muted-foreground tabular-nums">
        ↑{span.input_tokens ?? 0} ↓{span.output_tokens ?? 0}
      </span>
    </li>
  );
}
