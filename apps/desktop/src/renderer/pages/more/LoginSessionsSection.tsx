import { Badge, Button } from "@/components/ui";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import {
  sessionDeviceLabel,
  sessionLastActiveLabel,
} from "@/lib/sessionDeviceLabel";
import { notifySuccess } from "@/lib/toast";
import { ApiError } from "@/services/api";
import {
  type SessionSummary,
  listSessions,
  logout,
  revokeOtherSessions,
  revokeSession,
} from "@/services/auth";
import { useAuthStore } from "@/stores/auth";
import { Loader2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

function errMsg(e: unknown, fallback: string): string {
  return e instanceof ApiError ? (e.serverMessage ?? fallback) : fallback;
}

type ConfirmTarget =
  | { kind: "one"; session: SessionSummary }
  | { kind: "others" };

/**
 * 登录设备 — list active refresh-token families and revoke one / all others.
 * Placed on 账户设置 between 修改密码 and 危险区域.
 */
export function LoginSessionsSection() {
  const [sessions, setSessions] = useState<SessionSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<ConfirmTarget | null>(null);

  const refresh = useCallback(async () => {
    setLoadError(null);
    setActionError(null);
    try {
      const res = await listSessions();
      setSessions(res.data ?? []);
    } catch (e) {
      setLoadError(errMsg(e, "加载失败，请重试"));
    }
  }, []);

  useEffect(() => {
    let alive = true;
    setLoading(true);
    void listSessions()
      .then((res) => {
        if (!alive) return;
        setSessions(res.data ?? []);
        setLoadError(null);
      })
      .catch((e) => {
        if (alive) setLoadError(errMsg(e, "加载失败，请重试"));
      })
      .finally(() => {
        if (alive) setLoading(false);
      });
    return () => {
      alive = false;
    };
  }, []);

  const runConfirmed = async () => {
    if (!confirm) return;
    const target = confirm;
    setConfirm(null);
    setActionError(null);

    if (target.kind === "others") {
      setBusyId("others");
      try {
        await revokeOtherSessions();
        notifySuccess("已退出其他所有设备");
        await refresh();
      } catch (e) {
        setActionError(errMsg(e, "操作失败，请重试"));
      } finally {
        setBusyId(null);
      }
      return;
    }

    const { session } = target;
    if (session.current) {
      setBusyId(session.id);
      try {
        // Current device → reuse the same logout clear-state path as UserMenu.
        try {
          await logout();
        } catch {
          /* clear the session client-side regardless of the network result */
        }
        useAuthStore.getState().setUnauthenticated();
      } finally {
        setBusyId(null);
      }
      return;
    }

    setBusyId(session.id);
    try {
      await revokeSession(session.id);
      notifySuccess("已退出该设备");
      await refresh();
    } catch (e) {
      setActionError(errMsg(e, "操作失败，请重试"));
    } finally {
      setBusyId(null);
    }
  };

  const showRevokeOthers = sessions.length > 1;
  const actionBusy = busyId !== null;

  return (
    <section>
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-foreground">登录设备</h2>
          <p className="mt-1 text-xs text-muted-foreground">
            查看当前账号的活跃登录，并可退出指定设备。
          </p>
        </div>
        {showRevokeOthers && !loading && !loadError && (
          <Button
            variant="danger"
            size="md"
            className="shrink-0"
            disabled={actionBusy}
            onClick={() => setConfirm({ kind: "others" })}
          >
            退出其他所有设备
          </Button>
        )}
      </div>

      <div className="mt-3 rounded-xl border border-border bg-card p-4">
        {loading ? (
          <div className="flex items-center gap-2 text-sm text-muted-foreground">
            <Loader2 size={16} className="animate-spin" />
            加载中…
          </div>
        ) : loadError ? (
          <div className="flex flex-col items-start gap-2">
            <p className="text-sm text-destructive">{loadError}</p>
            <Button
              variant="neutral"
              size="md"
              onClick={() => {
                setLoading(true);
                void refresh().finally(() => setLoading(false));
              }}
            >
              重试
            </Button>
          </div>
        ) : sessions.length === 0 ? (
          <p className="text-sm text-muted-foreground">暂无活跃登录设备</p>
        ) : (
          <ul className="divide-y divide-border">
            {sessions.map((s) => (
              <SessionRow
                key={s.id}
                session={s}
                busy={busyId === s.id}
                disabled={actionBusy}
                onRevoke={() => setConfirm({ kind: "one", session: s })}
              />
            ))}
          </ul>
        )}
        {actionError && (
          <p className="mt-3 text-xs text-destructive">{actionError}</p>
        )}
      </div>

      <ConfirmRevokeDialog
        target={confirm}
        onOpenChange={(open) => {
          if (!open) setConfirm(null);
        }}
        onConfirm={() => void runConfirmed()}
      />
    </section>
  );
}

function SessionRow({
  session,
  busy,
  disabled,
  onRevoke,
}: {
  session: SessionSummary;
  busy: boolean;
  disabled: boolean;
  onRevoke: () => void;
}) {
  const label = sessionDeviceLabel(session.platform, session.user_agent);
  const ip = session.ip?.trim() || "未知 IP";

  return (
    <li className="flex items-center gap-3 py-3 first:pt-0 last:pb-0">
      <div className="min-w-0 flex-1">
        <div className="flex flex-wrap items-center gap-2">
          <p className="text-sm text-foreground">{label}</p>
          {session.current && (
            <Badge tone="primary" pill>
              当前设备
            </Badge>
          )}
        </div>
        <p className="mt-0.5 text-xs text-muted-foreground">
          {ip}
          <span className="mx-1.5 text-border">·</span>
          最后活跃 {sessionLastActiveLabel(session.last_used_at)}
        </p>
      </div>
      <Button
        variant="danger"
        size="md"
        className="shrink-0"
        disabled={disabled}
        icon={busy ? <Loader2 size={14} className="animate-spin" /> : undefined}
        onClick={onRevoke}
      >
        退出
      </Button>
    </li>
  );
}

function ConfirmRevokeDialog({
  target,
  onOpenChange,
  onConfirm,
}: {
  target: ConfirmTarget | null;
  onOpenChange: (open: boolean) => void;
  onConfirm: () => void;
}) {
  const open = target !== null;
  const isOthers = target?.kind === "others";
  const isCurrent = target?.kind === "one" && target.session.current;

  const title = isOthers
    ? "退出其他所有设备？"
    : isCurrent
      ? "退出当前设备？"
      : "退出该设备？";
  const description = isOthers
    ? "其他设备上的登录将立即失效，需要重新登录。当前设备不受影响。"
    : isCurrent
      ? "退出后将返回登录页，需要重新登录才能继续使用。"
      : "该设备上的登录将立即失效，需要重新登录。";
  const confirmLabel = isOthers
    ? "退出其他设备"
    : isCurrent
      ? "退出并返回登录"
      : "确认退出";

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{title}</DialogTitle>
          <DialogDescription>{description}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button
            variant="neutral"
            className="h-9 px-4"
            onClick={() => onOpenChange(false)}
          >
            取消
          </Button>
          <Button
            variant="destructive"
            className="h-9 px-4"
            onClick={onConfirm}
          >
            {confirmLabel}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
