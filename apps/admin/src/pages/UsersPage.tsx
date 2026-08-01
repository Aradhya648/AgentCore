import { QuotaDialog } from "@/components/QuotaDialog";
import { UserDetail } from "@/components/UserDetail";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Input } from "@/components/ui/Input";
import { Spinner } from "@/components/ui/Spinner";
import { cn, fmtCny, nanoToYuan } from "@/lib/utils";
import { errorMessage } from "@/services/api";
import {
  type AdminUser,
  type AdminUserListItem,
  type SortOrder,
  type UserRole,
  type UserSort,
  type UserStatus,
  deleteUser,
  listUsers,
  updateUser,
} from "@/services/adminUsers";
import { useAuthStore } from "@/stores/auth";
import {
  ArrowDown,
  ArrowUp,
  ArrowUpDown,
  ChevronLeft,
  ChevronRight,
  RefreshCw,
  Search,
  X,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";

const PAGE_SIZE = 20;

function fmtDate(iso: string): string {
  const d = new Date(iso);
  return Number.isNaN(d.getTime()) ? "—" : d.toLocaleDateString();
}

function quotaSummary(u: AdminUser): string {
  if (u.is_unlimited) return "无限额";
  const tokens = u.quota_daily_tokens ?? "继承";
  const cost = u.quota_monthly_cost_cny ?? "继承";
  const req = u.quota_daily_requests ?? "继承";
  return `日 ${tokens} token · 月 ${typeof cost === "number" ? `¥${cost}` : cost} · ${req} 请求`;
}

/** A clickable column header: shows the active sort direction, neutral otherwise. */
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

export function UsersPage() {
  const { userId: detailId } = useParams<{ userId?: string }>();
  const navigate = useNavigate();
  const selfId = useAuthStore((s) => s.user?.id);
  const [users, setUsers] = useState<AdminUserListItem[]>([]);
  const [total, setTotal] = useState(0);
  const [page, setPage] = useState(1);
  const [q, setQ] = useState("");
  const [debouncedQ, setDebouncedQ] = useState("");
  // "all" = dimension unpinned (no query param sent).
  const [role, setRole] = useState<UserRole | "all">("all");
  const [status, setStatus] = useState<UserStatus | "all">("all");
  // Sort: newest registration first by default; 累计成本 is the other axis.
  const [sort, setSort] = useState<UserSort>("created_at");
  const [order, setOrder] = useState<SortOrder>("desc");
  // Off by default: 注销 accounts are anonymized tombstones, shown only for audit.
  const [includeDeleted, setIncludeDeleted] = useState(false);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [pending, setPending] = useState<Set<string>>(new Set());
  const [editing, setEditing] = useState<AdminUser | null>(null);
  // The account the operator is about to 注销 (null = no dialog open).
  const [deleting, setDeleting] = useState<AdminUser | null>(null);

  // Debounce the search box; a new query always restarts at page 1.
  useEffect(() => {
    const t = setTimeout(() => {
      setDebouncedQ(q);
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [q]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await listUsers({
        page,
        pageSize: PAGE_SIZE,
        q: debouncedQ,
        role: role === "all" ? undefined : role,
        status: status === "all" ? undefined : status,
        sort,
        order,
        includeDeleted,
      });
      setUsers(res.data);
      setTotal(res.total);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, [page, debouncedQ, role, status, sort, order, includeDeleted]);

  // Flip a column's sort: re-click toggles direction; a new key starts desc.
  // Any sort change restarts at page 1 (offset pagination over a new ordering).
  const toggleSort = useCallback(
    (key: UserSort) => {
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

  const patchRow = useCallback(
    async (
      user: AdminUser,
      patch: Parameters<typeof updateUser>[1],
      okMsg: string,
    ) => {
      setPending((prev) => new Set(prev).add(user.id));
      try {
        const updated = await updateUser(user.id, patch);
        setUsers((prev) =>
          prev.map((u) => (u.id === user.id ? { ...u, ...updated } : u)),
        );
        toast.success(okMsg);
      } catch (err) {
        toast.error(errorMessage(err));
      } finally {
        setPending((prev) => {
          const next = new Set(prev);
          next.delete(user.id);
          return next;
        });
      }
    },
    [],
  );

  // After 注销: the default roster hides tombstones, so drop the row (and adjust the
  // count); in the audit view, swap in the returned tombstone so its state is honest.
  const onDeleted = useCallback(
    (updated: AdminUser) => {
      setUsers((prev) =>
        includeDeleted
          ? prev.map((u) => (u.id === updated.id ? { ...u, ...updated } : u))
          : prev.filter((u) => u.id !== updated.id),
      );
      if (!includeDeleted) setTotal((t) => Math.max(0, t - 1));
      setDeleting(null);
    },
    [includeDeleted],
  );

  const totalPages = Math.max(1, Math.ceil(total / PAGE_SIZE));

  if (detailId) {
    return <UserDetail userId={detailId} onBack={() => navigate("/users")} />;
  }

  return (
    <div className="mx-auto max-w-[1200px] px-6 py-8">
      <div className="mb-6 flex items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-foreground">用户管理</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            共 {total} 个账号 · 禁用 / 启用、改角色、改配额
          </p>
        </div>
        <div className="flex flex-wrap items-center justify-end gap-2">
          <select
            value={role}
            onChange={(e) => {
              setRole(e.target.value as UserRole | "all");
              setPage(1);
            }}
            aria-label="按角色筛选"
            className="h-9 rounded-lg border border-input bg-card px-2 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <option value="all">全部角色</option>
            <option value="user">user</option>
            <option value="admin">admin</option>
          </select>
          <select
            value={status}
            onChange={(e) => {
              setStatus(e.target.value as UserStatus | "all");
              setPage(1);
            }}
            aria-label="按状态筛选"
            className="h-9 rounded-lg border border-input bg-card px-2 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring"
          >
            <option value="all">全部状态</option>
            <option value="active">活跃</option>
            <option value="disabled">已停用</option>
          </select>
          <label className="flex cursor-pointer select-none items-center gap-2 text-muted-foreground text-sm">
            <input
              type="checkbox"
              checked={includeDeleted}
              onChange={(e) => {
                setIncludeDeleted(e.target.checked);
                setPage(1);
              }}
              className="size-4 rounded border-input accent-primary"
            />
            显示已注销
          </label>
          <div className="relative">
            <Search
              size={14}
              className="-translate-y-1/2 pointer-events-none absolute top-1/2 left-3 text-muted-foreground"
            />
            <Input
              type="search"
              placeholder="搜索用户名 / 昵称"
              value={q}
              onChange={(e) => setQ(e.target.value)}
              className="w-64 pl-8"
            />
          </div>
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

      <div className="overflow-hidden rounded-xl border border-border bg-card">
        <table className="w-full text-sm">
          <thead>
            <tr className="border-border border-b bg-muted/40 text-left text-xs text-muted-foreground">
              <th className="px-4 py-2.5 font-medium">用户</th>
              <th className="px-4 py-2.5 font-medium">角色</th>
              <th className="px-4 py-2.5 font-medium">状态</th>
              <th className="px-4 py-2.5 font-medium">配额</th>
              <th className="px-4 py-2.5 font-medium">
                <SortHeader
                  label="注册时间"
                  active={sort === "created_at"}
                  order={order}
                  onClick={() => toggleSort("created_at")}
                />
              </th>
              <th className="px-4 py-2.5 text-right font-medium">
                <SortHeader
                  label="累计成本"
                  active={sort === "cost"}
                  order={order}
                  align="right"
                  onClick={() => toggleSort("cost")}
                />
              </th>
              <th className="px-4 py-2.5 text-right font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {users.map((u) => {
              const isSelf = u.id === selfId;
              const busy = pending.has(u.id);
              // 注销 accounts are anonymized tombstones: surfaced for audit, but
              // their role/quota/status controls are meaningless (and re-enabling a
              // `deleted_<id>` account would be wrong), so the row is read-only.
              const isDeleted = !!u.deleted_at;
              return (
                <tr
                  key={u.id}
                  className={cn(
                    "border-border border-b last:border-0 hover:bg-accent/40",
                    isDeleted && "opacity-60",
                  )}
                >
                  <td className="px-4 py-3">
                    {isDeleted ? (
                      <div>
                        <div className="font-medium text-foreground">
                          {u.display_name || u.username}
                        </div>
                        <div className="text-muted-foreground text-xs">
                          @{u.username}
                        </div>
                      </div>
                    ) : (
                      <button
                        type="button"
                        onClick={() => navigate(`/users/${u.id}`)}
                        title="查看用户详情"
                        className="rounded text-left outline-none focus-visible:ring-2 focus-visible:ring-ring"
                      >
                        <div className="font-medium text-foreground hover:underline">
                          {u.display_name || u.username}
                          {isSelf && (
                            <span className="ml-2 text-muted-foreground text-xs">
                              (我)
                            </span>
                          )}
                        </div>
                        <div className="text-muted-foreground text-xs">
                          @{u.username}
                          {u.email ? ` · ${u.email}` : ""}
                        </div>
                      </button>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {isDeleted ? (
                      <span className="text-muted-foreground text-xs">
                        {u.role}
                      </span>
                    ) : (
                      <select
                        value={u.role}
                        disabled={isSelf || busy}
                        onChange={(e) =>
                          void patchRow(
                            u,
                            { role: e.target.value as "user" | "admin" },
                            "角色已更新",
                          )
                        }
                        title={isSelf ? "不能修改自己的角色" : undefined}
                        className="h-8 rounded-lg border border-input bg-card px-2 text-sm text-foreground outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:opacity-50"
                      >
                        <option value="user">user</option>
                        <option value="admin">admin</option>
                      </select>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    {isDeleted ? (
                      <Badge tone="neutral">已注销</Badge>
                    ) : u.status === "active" ? (
                      <Badge tone="success">活跃</Badge>
                    ) : (
                      <Badge tone="destructive">已停用</Badge>
                    )}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground text-xs">
                    {isDeleted ? "—" : quotaSummary(u)}
                  </td>
                  <td className="px-4 py-3 text-muted-foreground text-xs">
                    {fmtDate(u.created_at)}
                  </td>
                  <td className="px-4 py-3 text-right text-foreground text-xs tabular-nums">
                    {fmtCny(nanoToYuan(u.cost_total))}
                  </td>
                  <td className="px-4 py-3">
                    {isDeleted ? (
                      <div className="text-right text-muted-foreground text-xs">
                        —
                      </div>
                    ) : (
                      <div className="flex items-center justify-end gap-2">
                        <Button
                          variant="outline"
                          size="sm"
                          onClick={() => setEditing(u)}
                          disabled={busy}
                        >
                          配额
                        </Button>
                        {u.status === "active" ? (
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={isSelf || busy}
                            title={isSelf ? "不能停用自己" : undefined}
                            className="text-destructive"
                            onClick={() =>
                              void patchRow(
                                u,
                                { status: "disabled" },
                                "账号已停用",
                              )
                            }
                          >
                            {busy ? <Spinner /> : "停用"}
                          </Button>
                        ) : (
                          <Button
                            variant="outline"
                            size="sm"
                            disabled={busy}
                            onClick={() =>
                              void patchRow(u, { status: "active" }, "账号已启用")
                            }
                          >
                            {busy ? <Spinner /> : "启用"}
                          </Button>
                        )}
                        <Button
                          variant="ghost"
                          size="sm"
                          className="text-destructive"
                          disabled={isSelf || busy}
                          title={isSelf ? "不能注销自己" : "注销账号（不可恢复）"}
                          onClick={() => setDeleting(u)}
                        >
                          注销
                        </Button>
                      </div>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>

        {loading && (
          <div className="flex items-center justify-center gap-2 py-10 text-muted-foreground text-sm">
            <Spinner />
            加载中…
          </div>
        )}
        {!loading && error && (
          <div className="flex flex-col items-center gap-3 py-10 text-sm">
            <span className="text-destructive">{error}</span>
            <Button variant="outline" size="sm" onClick={() => void load()}>
              重试
            </Button>
          </div>
        )}
        {!loading && !error && users.length === 0 && (
          <div className="py-10 text-center text-muted-foreground text-sm">
            没有匹配的用户
          </div>
        )}
      </div>

      <div className="mt-4 flex items-center justify-between text-muted-foreground text-sm">
        <span>
          第 {page} / {totalPages} 页
        </span>
        <div className="flex items-center gap-2">
          <Button
            variant="outline"
            size="sm"
            disabled={page <= 1 || loading}
            onClick={() => setPage((p) => Math.max(1, p - 1))}
          >
            <ChevronLeft size={14} />
            上一页
          </Button>
          <Button
            variant="outline"
            size="sm"
            disabled={page >= totalPages || loading}
            onClick={() => setPage((p) => p + 1)}
          >
            下一页
            <ChevronRight size={14} />
          </Button>
        </div>
      </div>

      {editing && (
        <QuotaDialog
          user={editing}
          onClose={() => setEditing(null)}
          onSaved={(updated) => {
            setUsers((prev) =>
              prev.map((u) => (u.id === updated.id ? { ...u, ...updated } : u)),
            );
            setEditing(null);
          }}
        />
      )}

      {deleting && (
        <DeleteUserDialog
          user={deleting}
          onClose={() => setDeleting(null)}
          onDeleted={onDeleted}
        />
      )}
    </div>
  );
}

function DeleteUserDialog({
  user,
  onClose,
  onDeleted,
}: {
  user: AdminUser;
  onClose: () => void;
  onDeleted: (updated: AdminUser) => void;
}) {
  const [saving, setSaving] = useState(false);

  const handleDelete = async () => {
    if (saving) return;
    setSaving(true);
    try {
      const updated = await deleteUser(user.id);
      toast.success("账号已注销");
      onDeleted(updated);
    } catch (err) {
      toast.error(errorMessage(err));
      setSaving(false);
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-overlay px-6"
      onMouseDown={onClose}
    >
      <div
        className="w-full max-w-md rounded-xl border border-border bg-card p-5 shadow-lg"
        onMouseDown={(e) => e.stopPropagation()}
      >
        <div className="mb-4 flex items-start justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold text-foreground">注销账号</h2>
            <p className="mt-0.5 text-xs text-muted-foreground">
              此操作不可恢复，请确认后再继续
            </p>
          </div>
          <button
            type="button"
            onClick={onClose}
            aria-label="关闭"
            className="flex size-7 items-center justify-center rounded-lg text-muted-foreground hover:bg-accent hover:text-accent-foreground"
          >
            <X size={16} />
          </button>
        </div>

        <p className="text-sm text-muted-foreground">
          将注销{" "}
          <span className="font-medium text-foreground">
            {user.display_name || user.username}
          </span>
          （@{user.username}）：账号
          <span className="font-medium text-foreground">匿名化</span>
          （用户名 / 邮箱 / 头像清除）、
          <span className="font-medium text-foreground">立即登出所有设备</span>
          ，其对话与分享一并清理、BYOK 密钥删除。账单记录保留。
        </p>

        <div className="mt-4 flex justify-end gap-2">
          <Button variant="outline" size="sm" onClick={onClose} disabled={saving}>
            取消
          </Button>
          <Button
            variant="destructive"
            size="sm"
            onClick={() => void handleDelete()}
            disabled={saving}
          >
            {saving && <Spinner />}
            确认注销
          </Button>
        </div>
      </div>
    </div>
  );
}
