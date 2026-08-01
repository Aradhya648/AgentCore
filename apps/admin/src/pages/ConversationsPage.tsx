import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Spinner } from "@/components/ui/Spinner";
import { CopyableId } from "@/components/CopyableId";
import {
  cn,
  fmtCny,
  fmtCompact,
  fmtInt,
  fmtMs,
  fmtTime,
  nanoUsdToCny,
} from "@/lib/utils";
import { errorMessage } from "@/services/api";
import {
  type AdminConversationListItem,
  type AdminTurnListItem,
  type ConversationSort,
  type SortOrder,
  type TurnStatus,
  listConversations,
  listTurns,
} from "@/services/adminConversations";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Search,
  Users,
} from "lucide-react";
import { type FormEvent, useCallback, useEffect, useState } from "react";
import {
  Navigate,
  useLocation,
  useNavigate,
  useParams,
  useSearchParams,
} from "react-router-dom";

const PAGE_SIZE = 20;

type Segment = "conversations" | "turns";

function credentialSourceLabel(
  source: "user" | "platform" | null | undefined,
): string | null {
  if (source === "user") return "BYOK";
  if (source === "platform") return "平台";
  return null;
}

/** UTC day bounds for ``since`` / ``until`` query params (date input → ISO). */
function dateToSince(isoDate: string): string {
  return `${isoDate}T00:00:00.000Z`;
}

function dateToUntil(isoDate: string): string {
  return `${isoDate}T23:59:59.999Z`;
}

function SortHeader({
  label,
  active,
  order,
  align = "left",
  onClick,
}: {
  label: string;
  active: boolean;
  order: SortOrder;
  align?: "left" | "right";
  onClick: () => void;
}) {
  const Icon = !active ? ArrowUpDown : order === "asc" ? ArrowUp : ArrowDown;
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "inline-flex items-center gap-1 rounded font-medium outline-none transition-colors hover:text-foreground focus-visible:ring-2 focus-visible:ring-ring",
        active && "text-foreground",
        align === "right" && "flex-row-reverse",
      )}
      aria-label={`按${label}排序`}
    >
      {label}
      <Icon size={12} className={cn(!active && "opacity-50")} />
    </button>
  );
}

/**
 * 对话: platform-wide AI conversation index (会话 roster + 回合 feed).
 * Session rows for browse/filter; turn rows for finer-grained triage — both
 * drill into 会话复盘.
 */
export function ConversationsPage() {
  const { segment: segmentParam } = useParams<{ segment: string }>();
  const [searchParams, setSearchParams] = useSearchParams();
  const navigate = useNavigate();
  const location = useLocation();

  if (segmentParam !== "conversations" && segmentParam !== "turns") {
    return <Navigate to="/conversations/conversations" replace />;
  }

  const segment: Segment = segmentParam;
  const userIdFilter = searchParams.get("user_id") ?? undefined;
  const [jumpInput, setJumpInput] = useState("");
  const [jumpBusy, setJumpBusy] = useState(false);

  const openReplay = (conversationId: string, opts?: { trace?: string }) => {
    const qs = opts?.trace
      ? `?trace=${encodeURIComponent(opts.trace)}`
      : "";
    navigate(`/replay/${conversationId}${qs}`, {
      state: { from: location.pathname },
    });
  };

  const submitJump = async (e: FormEvent) => {
    e.preventDefault();
    const raw = jumpInput.trim();
    if (!raw) return;
    setJumpBusy(true);
    try {
      // Prefer trace_id resolution (32-hex) → conversation + highlight; else treat as
      // conversation_id (same shape as many ids — operator paste either works).
      if (/^[0-9a-f]{32}$/i.test(raw)) {
        const byTrace = await listTurns({
          page: 1,
          pageSize: 1,
          traceId: raw,
        });
        const hit = byTrace.data[0];
        if (hit) {
          openReplay(hit.conversation_id, { trace: raw });
          return;
        }
      }
      openReplay(raw);
    } catch (err) {
      // Fall through to conversation_id open; replay page surfaces 404.
      void err;
      openReplay(raw);
    } finally {
      setJumpBusy(false);
    }
  };

  const setSegment = (s: Segment) => {
    const next = new URLSearchParams(searchParams);
    navigate(`/conversations/${s}?${next.toString()}`);
  };

  const clearUserFilter = () => {
    const next = new URLSearchParams(searchParams);
    next.delete("user_id");
    setSearchParams(next);
  };

  const subtitle =
    segment === "conversations"
      ? "全站 AI 会话索引 · 按用户 / 标题 / 多 Agent 筛选 · 点击行进入复盘"
      : "全站回合流水 · 按状态 / 多 Agent 筛选 · 方便排障与优化";

  return (
    <div className="mx-auto max-w-[1200px] px-6 py-8">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-foreground">对话</h1>
          <p className="mt-1 text-sm text-muted-foreground">{subtitle}</p>
          {userIdFilter && (
            <p className="mt-2 text-sm text-muted-foreground">
              筛选用户{" "}
              <code className="rounded bg-muted px-1.5 py-0.5 font-mono text-xs">
                {userIdFilter}
              </code>
              <button
                type="button"
                onClick={clearUserFilter}
                className="ml-2 text-primary text-xs underline-offset-2 hover:underline"
              >
                清除
              </button>
            </p>
          )}
        </div>
        <div className="flex flex-wrap items-center gap-2">
          <SegmentToggle value={segment} onChange={setSegment} />
          <form onSubmit={(e) => void submitJump(e)} className="flex items-center gap-2">
            <Input
              value={jumpInput}
              onChange={(e) => setJumpInput(e.target.value)}
              placeholder="conversation_id / trace_id…"
              className="w-56 font-mono text-xs"
            />
            <Button
              type="submit"
              variant="outline"
              size="sm"
              disabled={!jumpInput.trim() || jumpBusy}
            >
              复盘
            </Button>
          </form>
        </div>
      </div>

      {segment === "conversations" ? (
        <ConversationsPanel
          userId={userIdFilter}
          onOpenReplay={openReplay}
        />
      ) : (
        <TurnsPanel userId={userIdFilter} onOpenReplay={openReplay} />
      )}
    </div>
  );
}

function SegmentToggle({
  value,
  onChange,
}: {
  value: Segment;
  onChange: (s: Segment) => void;
}) {
  const items: { id: Segment; label: string }[] = [
    { id: "conversations", label: "会话" },
    { id: "turns", label: "回合" },
  ];
  return (
    <div className="inline-flex items-center rounded-lg border border-border p-0.5">
      {items.map((it) => (
        <button
          key={it.id}
          type="button"
          aria-pressed={value === it.id}
          onClick={() => onChange(it.id)}
          className={cn(
            "h-7 rounded-lg px-3 text-sm font-medium outline-none transition-colors focus-visible:ring-2 focus-visible:ring-ring",
            value === it.id
              ? "bg-accent text-accent-foreground"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {it.label}
        </button>
      ))}
    </div>
  );
}

function ConversationsPanel({
  userId,
  onOpenReplay,
}: {
  userId?: string;
  onOpenReplay: (id: string, opts?: { trace?: string }) => void;
}) {
  const [rows, setRows] = useState<AdminConversationListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [cnyPerUsd, setCnyPerUsd] = useState(0);
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  const [hasErrors, setHasErrors] = useState<"all" | "yes" | "no">("all");
  const [hasDelegated, setHasDelegated] = useState<"all" | "yes" | "no">("all");
  const [includeDeleted, setIncludeDeleted] = useState(true);
  const [sinceDate, setSinceDate] = useState("");
  const [untilDate, setUntilDate] = useState("");
  const [sort, setSort] = useState<ConversationSort>("updated_at");
  const [order, setOrder] = useState<SortOrder>("desc");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedQ(q);
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [q]);

  useEffect(() => {
    setPage(1);
  }, [userId]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listConversations({
        page,
        pageSize: PAGE_SIZE,
        q: debouncedQ,
        userId,
        hasErrors:
          hasErrors === "yes" ? true : hasErrors === "no" ? false : undefined,
        hasDelegated:
          hasDelegated === "yes"
            ? true
            : hasDelegated === "no"
              ? false
              : undefined,
        includeDeleted,
        since: sinceDate ? dateToSince(sinceDate) : undefined,
        until: untilDate ? dateToUntil(untilDate) : undefined,
        sort,
        order,
      });
      setRows(res.data);
      setTotal(res.total);
      setCnyPerUsd(res.cny_per_usd);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [
    page,
    debouncedQ,
    userId,
    hasErrors,
    hasDelegated,
    includeDeleted,
    sinceDate,
    untilDate,
    sort,
    order,
  ]);

  const toggleSort = useCallback(
    (key: ConversationSort) => {
      if (sort === key) {
        setOrder((o) => (o === "asc" ? "desc" : "asc"));
      } else {
        setSort(key);
        setOrder("desc");
      }
      setPage(1);
    },
    [sort],
  );

  useEffect(() => {
    void load();
  }, [load]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <div className="relative min-w-[200px] flex-1">
          <Search
            size={14}
            className="pointer-events-none absolute top-1/2 left-3 -translate-y-1/2 text-muted-foreground"
          />
          <Input
            value={q}
            onChange={(e) => setQ(e.target.value)}
            placeholder="搜索会话标题…"
            className="pl-8"
          />
        </div>
        <select
          value={hasErrors}
          onChange={(e) => {
            setHasErrors(e.target.value as "all" | "yes" | "no");
            setPage(1);
          }}
          className="h-9 rounded-lg border border-input bg-background px-3 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <option value="all">全部会话</option>
          <option value="yes">仅有错误</option>
          <option value="no">无错误</option>
        </select>
        <select
          value={hasDelegated}
          onChange={(e) => {
            setHasDelegated(e.target.value as "all" | "yes" | "no");
            setPage(1);
          }}
          className="h-9 rounded-lg border border-input bg-background px-3 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <option value="all">全部协作</option>
          <option value="yes">仅多 Agent</option>
          <option value="no">无委派</option>
        </select>
        <Input
          type="date"
          value={sinceDate}
          onChange={(e) => {
            setSinceDate(e.target.value);
            setPage(1);
          }}
          className="w-36"
          title="更新起始（UTC 日）"
          aria-label="更新起始日期"
        />
        <Input
          type="date"
          value={untilDate}
          onChange={(e) => {
            setUntilDate(e.target.value);
            setPage(1);
          }}
          className="w-36"
          title="更新截止（UTC 日）"
          aria-label="更新截止日期"
        />
        <label className="flex items-center gap-2 text-muted-foreground text-sm">
          <input
            type="checkbox"
            checked={includeDeleted}
            onChange={(e) => {
              setIncludeDeleted(e.target.checked);
              setPage(1);
            }}
            className="rounded border-input"
          />
          含已删除
        </label>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void load()}
          disabled={loading}
          aria-label="刷新"
        >
          <RefreshCw size={14} className={cn(loading && "animate-spin")} />
        </Button>
      </div>

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

      {!loading && !error && (
        <section className="overflow-hidden rounded-xl border border-border bg-card">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-border border-b bg-muted/40 text-left text-xs text-muted-foreground">
                <th className="px-5 py-2.5 font-medium">标题</th>
                <th className="px-5 py-2.5 font-medium">用户</th>
                <th className="px-5 py-2.5 text-right font-medium">消息</th>
                <th className="px-5 py-2.5 text-right font-medium">回合</th>
                <th className="px-5 py-2.5 text-right font-medium">错误</th>
                <th className="px-5 py-2.5 text-right font-medium">
                  <SortHeader
                    label="委派"
                    active={sort === "delegated"}
                    order={order}
                    align="right"
                    onClick={() => toggleSort("delegated")}
                  />
                </th>
                <th className="px-5 py-2.5 text-right font-medium">
                  <SortHeader
                    label="成本"
                    active={sort === "cost"}
                    order={order}
                    align="right"
                    onClick={() => toggleSort("cost")}
                  />
                </th>
                <th className="px-5 py-2.5 font-medium">
                  <SortHeader
                    label="创建"
                    active={sort === "created_at"}
                    order={order}
                    onClick={() => toggleSort("created_at")}
                  />
                </th>
                <th className="px-5 py-2.5 font-medium">
                  <SortHeader
                    label="更新"
                    active={sort === "updated_at"}
                    order={order}
                    onClick={() => toggleSort("updated_at")}
                  />
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((c) => (
                <tr
                  key={c.id}
                  onClick={() => onOpenReplay(c.id)}
                  className="cursor-pointer border-border border-b align-top last:border-0 hover:bg-accent/40"
                >
                  <td className="max-w-xs px-5 py-3 text-foreground">
                    <div className="line-clamp-2 break-words">
                      {c.title || (
                        <span className="text-muted-foreground italic">
                          未命名会话
                        </span>
                      )}
                    </div>
                    <div className="mt-1 flex flex-wrap gap-1">
                      {(c.delegated_turns ?? 0) > 0 && (
                        <Badge tone="primary">
                          <Users size={10} className="mr-0.5" />
                          多 Agent
                          {(c.workers ?? 0) > 0 ? ` · ${c.workers}` : ""}
                        </Badge>
                      )}
                      {c.deleted_at && (
                        <Badge tone="neutral">会话已删</Badge>
                      )}
                      {c.user_deleted_at && (
                        <Badge tone="warning">用户已注销</Badge>
                      )}
                    </div>
                  </td>
                  <td className="px-5 py-3">
                    <div className="font-medium text-foreground">
                      {c.display_name || c.username || "—"}
                    </div>
                    {c.username && (
                      <div className="text-muted-foreground text-xs">
                        @{c.username}
                      </div>
                    )}
                  </td>
                  <td className="px-5 py-3 text-right text-muted-foreground tabular-nums">
                    {fmtInt(c.messages)}
                  </td>
                  <td className="px-5 py-3 text-right text-muted-foreground tabular-nums">
                    {fmtInt(c.turns)}
                  </td>
                  <td className="px-5 py-3 text-right tabular-nums">
                    {c.errors > 0 ? (
                      <span className="text-destructive">{fmtInt(c.errors)}</span>
                    ) : (
                      <span className="text-muted-foreground">0</span>
                    )}
                  </td>
                  <td className="px-5 py-3 text-right text-muted-foreground tabular-nums">
                    {(c.delegated_turns ?? 0) > 0
                      ? fmtInt(c.delegated_turns)
                      : "—"}
                  </td>
                  <td className="px-5 py-3 text-right text-muted-foreground tabular-nums">
                    {c.cost_total > 0
                      ? fmtCny(nanoUsdToCny(c.cost_total, cnyPerUsd))
                      : "—"}
                  </td>
                  <td className="whitespace-nowrap px-5 py-3 text-muted-foreground tabular-nums">
                    {fmtTime(c.created_at)}
                  </td>
                  <td className="whitespace-nowrap px-5 py-3 text-muted-foreground tabular-nums">
                    {fmtTime(c.updated_at)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
          {rows.length === 0 && (
            <div className="py-10 text-center text-muted-foreground text-sm">
              暂无会话
            </div>
          )}
        </section>
      )}

      {!loading && !error && total > PAGE_SIZE && (
        <Pagination
          page={page}
          totalPages={totalPages}
          total={total}
          onPageChange={setPage}
        />
      )}
    </div>
  );
}

function TurnsPanel({
  userId,
  onOpenReplay,
}: {
  userId?: string;
  onOpenReplay: (id: string, opts?: { trace?: string }) => void;
}) {
  const [rows, setRows] = useState<AdminTurnListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [status, setStatus] = useState<TurnStatus | "all">("all");
  const [delegatedOnly, setDelegatedOnly] = useState(false);
  const [includeDeleted, setIncludeDeleted] = useState(true);
  const [sinceDate, setSinceDate] = useState("");
  const [untilDate, setUntilDate] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    setPage(1);
  }, [userId]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listTurns({
        page,
        pageSize: PAGE_SIZE,
        userId,
        status: status === "all" ? undefined : status,
        delegated: delegatedOnly ? true : undefined,
        since: sinceDate ? dateToSince(sinceDate) : undefined,
        until: untilDate ? dateToUntil(untilDate) : undefined,
        includeDeletedConversations: includeDeleted,
      });
      setRows(res.data);
      setTotal(res.total);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [page, userId, status, delegatedOnly, includeDeleted, sinceDate, untilDate]);

  useEffect(() => {
    void load();
  }, [load]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="flex flex-col gap-4">
      <div className="flex flex-wrap items-center gap-2">
        <select
          value={status}
          onChange={(e) => {
            setStatus(e.target.value as TurnStatus | "all");
            setPage(1);
          }}
          className="h-9 rounded-lg border border-input bg-background px-3 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
        >
          <option value="all">全部状态</option>
          <option value="ok">成功</option>
          <option value="error">失败</option>
        </select>
        <label className="flex h-9 items-center gap-2 rounded-lg border border-input bg-background px-3 text-sm text-foreground">
          <input
            type="checkbox"
            checked={delegatedOnly}
            onChange={(e) => {
              setDelegatedOnly(e.target.checked);
              setPage(1);
            }}
            className="rounded border-input"
          />
          仅多 Agent
        </label>
        <Input
          type="date"
          value={sinceDate}
          onChange={(e) => {
            setSinceDate(e.target.value);
            setPage(1);
          }}
          className="w-36"
          title="回合起始（UTC 日）"
          aria-label="回合起始日期"
        />
        <Input
          type="date"
          value={untilDate}
          onChange={(e) => {
            setUntilDate(e.target.value);
            setPage(1);
          }}
          className="w-36"
          title="回合截止（UTC 日）"
          aria-label="回合截止日期"
        />
        <label className="flex items-center gap-2 text-muted-foreground text-sm">
          <input
            type="checkbox"
            checked={includeDeleted}
            onChange={(e) => {
              setIncludeDeleted(e.target.checked);
              setPage(1);
            }}
            className="rounded border-input"
          />
          含已删除会话
        </label>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void load()}
          disabled={loading}
          aria-label="刷新"
        >
          <RefreshCw size={14} className={cn(loading && "animate-spin")} />
        </Button>
      </div>

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

      {!loading && !error && (
        <section className="overflow-hidden rounded-xl border border-border bg-card">
          <table className="w-full text-sm">
            <thead>
              <tr className="border-border border-b bg-muted/40 text-left text-xs text-muted-foreground">
                <th className="px-5 py-2.5 font-medium">时间</th>
                <th className="px-5 py-2.5 font-medium">trace_id</th>
                <th className="px-5 py-2.5 font-medium">用户</th>
                <th className="px-5 py-2.5 font-medium">会话</th>
                <th className="px-5 py-2.5 font-medium">状态</th>
                <th className="px-5 py-2.5 font-medium">详情</th>
                <th className="px-5 py-2.5 text-right font-medium">轮数</th>
                <th className="px-5 py-2.5 text-right font-medium">Token</th>
                <th className="px-5 py-2.5 text-right font-medium">耗时</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((t) => {
                const isError = t.status === "error";
                const credLabel = credentialSourceLabel(t.credential_source);
                return (
                  <tr
                    key={t.turn_id}
                    onClick={() =>
                      onOpenReplay(t.conversation_id, {
                        trace: t.trace_id ?? undefined,
                      })
                    }
                    className="cursor-pointer border-border border-b align-top last:border-0 hover:bg-accent/40"
                  >
                    <td className="whitespace-nowrap px-5 py-3 text-muted-foreground tabular-nums">
                      {fmtTime(t.created_at)}
                    </td>
                    <td className="px-5 py-3">
                      {t.trace_id ? (
                        <CopyableId
                          value={t.trace_id}
                          label="trace_id"
                          className="max-w-[7rem]"
                          titleHint={`${t.trace_id}（点击复制 → log_timeline --trace / --pack）`}
                        />
                      ) : (
                        <span className="text-muted-foreground">—</span>
                      )}
                    </td>
                    <td className="px-5 py-3">
                      <div className="font-medium text-foreground">
                        {t.display_name || t.username || "—"}
                      </div>
                      {t.username && (
                        <div className="text-muted-foreground text-xs">
                          @{t.username}
                        </div>
                      )}
                    </td>
                    <td className="max-w-xs px-5 py-3 text-foreground">
                      <div className="line-clamp-2 break-words">
                        {t.conversation_title || (
                          <span className="text-muted-foreground italic">
                            未命名会话
                          </span>
                        )}
                      </div>
                      {t.conversation_deleted_at && (
                        <Badge tone="neutral" className="mt-1">
                          会话已删
                        </Badge>
                      )}
                    </td>
                    <td className="px-5 py-3">
                      <div className="flex flex-col items-start gap-1">
                        <Badge tone={isError ? "destructive" : "success"}>
                          {isError ? "失败" : "成功"}
                        </Badge>
                        {t.delegated && (
                          <Badge tone="primary">
                            <Users size={10} className="mr-0.5" />
                            多 Agent · {t.workers}
                          </Badge>
                        )}
                        {credLabel && (
                          <Badge tone="neutral">{credLabel}</Badge>
                        )}
                        {(t.models?.length ?? 0) > 0 && (
                          <span
                            className="max-w-[9rem] text-muted-foreground text-[11px] leading-snug break-words"
                            title={t.models.join(", ")}
                          >
                            {t.models.join(", ")}
                          </span>
                        )}
                      </div>
                    </td>
                    <td className="max-w-xs px-5 py-3 text-muted-foreground">
                      <span className="line-clamp-2 break-words">
                        {isError
                          ? (t.error ?? t.finish_reason ?? "error")
                          : (t.finish_reason ?? "—")}
                      </span>
                    </td>
                    <td className="px-5 py-3 text-right text-muted-foreground tabular-nums">
                      {fmtInt(t.rounds)}
                    </td>
                    <td
                      className="px-5 py-3 text-right text-muted-foreground text-xs tabular-nums"
                      title={`输入 ${fmtInt(t.input_tokens)} · 输出 ${fmtInt(t.output_tokens)}`}
                    >
                      <div>{fmtCompact(t.input_tokens)} in</div>
                      <div>{fmtCompact(t.output_tokens)} out</div>
                    </td>
                    <td className="px-5 py-3 text-right text-muted-foreground tabular-nums">
                      {fmtMs(t.duration_ms)}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {rows.length === 0 && (
            <div className="py-10 text-center text-muted-foreground text-sm">
              暂无回合
            </div>
          )}
        </section>
      )}

      {!loading && !error && total > PAGE_SIZE && (
        <Pagination
          page={page}
          totalPages={totalPages}
          total={total}
          onPageChange={setPage}
        />
      )}
    </div>
  );
}

function Pagination({
  page,
  totalPages,
  total,
  onPageChange,
}: {
  page: number;
  totalPages: number;
  total: number;
  onPageChange: (p: number) => void;
}) {
  return (
    <div className="flex items-center justify-between text-muted-foreground text-sm">
      <span>
        共 {fmtInt(total)} 条 · 第 {page} / {totalPages} 页
      </span>
      <div className="flex items-center gap-1">
        <Button
          variant="outline"
          size="sm"
          disabled={page <= 1}
          onClick={() => onPageChange(page - 1)}
          aria-label="上一页"
        >
          <ChevronLeft size={16} />
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={page >= totalPages}
          onClick={() => onPageChange(page + 1)}
          aria-label="下一页"
        >
          <ChevronRight size={16} />
        </Button>
      </div>
    </div>
  );
}
