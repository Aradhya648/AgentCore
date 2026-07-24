import { CopyableId } from "@/components/CopyableId";
import { Markdown } from "@/components/Markdown";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import { cn, fmtCny, fmtInt, fmtMs, fmtTime, nanoUsdToCny } from "@/lib/utils";
import {
  type AdminConversationReplay,
  type ReplayMessage,
  type ReplaySpan,
  fetchConversationReplay,
} from "@/services/adminObservability";
import { errorMessage } from "@/services/api";
import { ArrowLeft, ChevronRight } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

const ROLE_LABEL: Record<string, string> = {
  user: "用户",
  assistant: "助手",
  system: "系统",
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
  const [data, setData] = useState<AdminConversationReplay | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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

  return (
    <div className="mx-auto max-w-4xl px-6 py-8">
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
        <div className="flex flex-col gap-5">
          <header className="rounded-xl border border-border bg-card p-5">
            <h1 className="text-xl font-semibold text-foreground">
              {data.conversation.title || "未命名会话"}
            </h1>
            <p className="mt-1 text-muted-foreground text-sm">
              {data.conversation.display_name || data.conversation.username || "未知用户"}
              {data.conversation.username && (
                <span className="text-muted-foreground">
                  {" "}
                  @{data.conversation.username}
                </span>
              )}
              {" · "}
              {fmtTime(data.conversation.created_at)}
            </p>
            <div className="mt-4 flex items-center gap-6 text-sm">
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
            </div>
            <CopyableId
              className="mt-3 block"
              value={data.conversation.id}
              label="conversation_id"
            />
          </header>

          <div className="flex flex-col gap-3">
            {data.messages.map((m) => (
              <MessageBlock
                key={m.id}
                message={m}
                cnyPerUsd={data.cny_per_usd}
              />
            ))}
            {data.messages.length === 0 && (
              <div className="rounded-xl border border-border bg-card py-10 text-center text-muted-foreground text-sm">
                该会话暂无消息
              </div>
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

function MessageBlock({
  message,
  cnyPerUsd,
}: {
  message: ReplayMessage;
  cnyPerUsd: number;
}) {
  const metrics = message.metrics;
  const isError = metrics?.status === "error";
  return (
    <div className="rounded-xl border border-border bg-card p-4">
      <div className="mb-2 flex items-center justify-between gap-3">
        <div className="flex items-center gap-2">
          <Badge tone={message.role === "assistant" ? "primary" : "neutral"}>
            {ROLE_LABEL[message.role] ?? message.role}
          </Badge>
          <span className="text-muted-foreground text-xs tabular-nums">
            {fmtTime(message.created_at)}
          </span>
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
              titleHint={`${metrics.trace_id}（点击复制，用于 grep logs/dev.jsonl）`}
            />
          )}
        </div>
      )}

      {message.spans.length > 0 && <SpanList spans={message.spans} />}
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
        onClick={() => setOpen((v) => !v)}
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
