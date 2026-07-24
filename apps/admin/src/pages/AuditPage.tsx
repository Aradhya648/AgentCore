import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import { cn } from "@/lib/utils";
import {
  AUDIT_ACTION_LABELS,
  type AdminAuditLogLine,
  listAuditLogs,
} from "@/services/adminAudit";
import { listUsers, type AdminUserListItem } from "@/services/adminUsers";
import { errorMessage } from "@/services/api";
import { ChevronLeft, ChevronRight, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { Link } from "react-router-dom";

const PAGE_SIZE = 50;

const ACTION_FILTERS: { value: string; label: string }[] = [
  { value: "", label: "全部操作" },
  { value: "user.update", label: "修改用户" },
  { value: "user.reset_password", label: "重置密码" },
  { value: "user.set_password", label: "设置密码" },
  { value: "account.change_password", label: "修改密码" },
  { value: "user.delete", label: "注销账号" },
  { value: "invite.create", label: "生成邀请码" },
  { value: "invite.batch_create", label: "批量生成" },
  { value: "invite.revoke", label: "撤销邀请码" },
  { value: "conversation.replay", label: "回放对话" },
];

function fmtTime(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleString();
}

function fmtDetail(detail: AdminAuditLogLine["detail"]): string {
  if (!detail || Object.keys(detail).length === 0) return "—";
  return JSON.stringify(detail);
}

function AuditTarget({ row }: { row: AdminAuditLogLine }) {
  if (!row.target_id) {
    return <span className="text-muted-foreground">—</span>;
  }

  const label = `${row.target_type} · ${row.target_id.slice(0, 8)}…`;

  if (row.target_type === "user") {
    return (
      <Link
        to={`/users/${row.target_id}`}
        className="font-mono text-xs text-primary underline-offset-2 hover:underline"
        title={row.target_id}
      >
        {label}
      </Link>
    );
  }

  if (row.target_type === "invite") {
    return (
      <span className="font-mono text-xs text-muted-foreground" title={row.target_id}>
        {label}
      </span>
    );
  }

  if (row.target_type === "conversation") {
    return (
      <Link
        to={`/replay/${row.target_id}`}
        className="font-mono text-xs text-primary underline-offset-2 hover:underline"
        title={row.target_id}
      >
        {label}
      </Link>
    );
  }

  return (
    <span className="font-mono text-xs text-muted-foreground" title={row.target_id}>
      {label}
    </span>
  );
}

export function AuditPage() {
  const [rows, setRows] = useState<AdminAuditLogLine[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [action, setAction] = useState("");
  const [actorId, setActorId] = useState("");
  const [operators, setOperators] = useState<AdminUserListItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    void listUsers({ page: 1, pageSize: 100, role: "admin" })
      .then((res) => setOperators(res.data))
      .catch(() => {
        /* actor filter degrades to “全部” if roster fails */
      });
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listAuditLogs({
        page,
        pageSize: PAGE_SIZE,
        action: action || undefined,
        actorId: actorId || undefined,
      });
      setRows(res.data);
      setTotal(res.total);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [page, action, actorId]);

  useEffect(() => {
    void load();
  }, [load]);

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  return (
    <div className="mx-auto max-w-[1200px] px-6 py-8">
      <div className="mb-6 flex flex-wrap items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-foreground">操作审计</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            管理员特权操作记录 · 共 {total} 条
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <select
            value={actorId}
            onChange={(e) => {
              setActorId(e.target.value);
              setPage(1);
            }}
            aria-label="按操作者筛选"
            className="h-9 max-w-[180px] rounded-lg border border-input bg-card px-2 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <option value="">全部操作者</option>
            {operators.map((op) => (
              <option key={op.id} value={op.id}>
                {op.display_name || op.username}
              </option>
            ))}
          </select>
          <select
            value={action}
            onChange={(e) => {
              setAction(e.target.value);
              setPage(1);
            }}
            aria-label="按操作类型筛选"
            className="h-9 rounded-lg border border-input bg-card px-2 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            {ACTION_FILTERS.map((f) => (
              <option key={f.value || "all"} value={f.value}>
                {f.label}
              </option>
            ))}
          </select>
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
        <>
          <div className="overflow-x-auto rounded-xl border border-border bg-card">
            <table className="w-full min-w-[720px] text-left text-sm">
              <thead>
                <tr className="border-border border-b text-muted-foreground">
                  <th className="px-4 py-3 font-medium">时间</th>
                  <th className="px-4 py-3 font-medium">操作者</th>
                  <th className="px-4 py-3 font-medium">操作</th>
                  <th className="px-4 py-3 font-medium">目标</th>
                  <th className="px-4 py-3 font-medium">详情</th>
                </tr>
              </thead>
              <tbody>
                {rows.length === 0 ? (
                  <tr>
                    <td
                      colSpan={5}
                      className="px-4 py-12 text-center text-muted-foreground"
                    >
                      暂无审计记录
                    </td>
                  </tr>
                ) : (
                  rows.map((row) => (
                    <tr
                      key={row.id}
                      className="border-border border-b last:border-b-0"
                    >
                      <td className="px-4 py-3 whitespace-nowrap tabular-nums text-muted-foreground">
                        {fmtTime(row.created_at)}
                      </td>
                      <td className="px-4 py-3">
                        <button
                          type="button"
                          className="text-foreground underline-offset-2 hover:text-primary hover:underline"
                          onClick={() => {
                            setActorId(row.actor_id);
                            setPage(1);
                          }}
                          title="按此操作者筛选"
                        >
                          {row.actor_username}
                        </button>
                      </td>
                      <td className="px-4 py-3">
                        <Badge tone="neutral">
                          {AUDIT_ACTION_LABELS[row.action] ?? row.action}
                        </Badge>
                      </td>
                      <td className="px-4 py-3">
                        <AuditTarget row={row} />
                      </td>
                      <td
                        className="max-w-[280px] truncate px-4 py-3 font-mono text-xs text-muted-foreground"
                        title={fmtDetail(row.detail)}
                      >
                        {fmtDetail(row.detail)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>

          {totalPages > 1 && (
            <div className="mt-4 flex items-center justify-center gap-3">
              <Button
                variant="outline"
                size="sm"
                disabled={page <= 1}
                onClick={() => setPage((p) => p - 1)}
              >
                <ChevronLeft size={14} />
              </Button>
              <span className="text-muted-foreground text-sm tabular-nums">
                {page} / {totalPages}
              </span>
              <Button
                variant="outline"
                size="sm"
                disabled={page >= totalPages}
                onClick={() => setPage((p) => p + 1)}
              >
                <ChevronRight size={14} />
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
