import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import { cn, fmtInt } from "@/lib/utils";
import {
  type AdminAgentAuditSummary,
  fetchAgentAuditSummary,
} from "@/services/adminAgentAudit";
import { errorMessage } from "@/services/api";
import { RefreshCw } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

/**
 * 观测看板审计聚合 widget：近 7 日失败事件、审批拒绝/超时、委派计划、采集降级。
 */
export function AuditSummaryWidget({ reloadKey = 0 }: { reloadKey?: number }) {
  const [data, setData] = useState<AdminAgentAuditSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      setData(await fetchAgentAuditSummary());
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load, reloadKey]);

  if (loading) {
    return (
      <section className="rounded-xl border border-border bg-card p-5">
        <div className="flex items-center gap-2 text-muted-foreground text-sm">
          <Spinner />
          加载审计聚合…
        </div>
      </section>
    );
  }

  if (error || !data) {
    return (
      <section className="flex flex-col items-center gap-3 rounded-xl border border-border bg-card p-5 text-sm">
        <span className="text-destructive">{error ?? "加载失败"}</span>
        <Button variant="outline" size="sm" onClick={() => void load()}>
          重试
        </Button>
      </section>
    );
  }

  const approvalTotal = data.approval_denied + data.approval_timeouts;

  return (
    <section className="rounded-xl border border-border bg-card p-5">
      <div className="mb-4 flex items-center justify-between gap-4">
        <div>
          <h2 className="text-base font-semibold text-foreground">
            Agent 审计 · 近 7 日
          </h2>
          <p className="mt-0.5 text-muted-foreground text-xs">
            多 Agent 协作副作用与审批健康（跨用户聚合，共{" "}
            {fmtInt(data.events)} 条事件）
          </p>
        </div>
        <Button
          variant="outline"
          size="sm"
          onClick={() => void load()}
          aria-label="刷新审计"
        >
          <RefreshCw size={14} />
        </Button>
      </div>

      <div className="mb-5 grid grid-cols-1 gap-4 sm:grid-cols-3">
        <MetricTile
          label="失败事件"
          value={fmtInt(data.failures)}
          tone={data.failures === 0 ? "success" : "destructive"}
        />
        <MetricTile
          label="审批拒绝"
          value={fmtInt(data.approval_denied)}
          tone={data.approval_denied === 0 ? "success" : "warning"}
        />
        <MetricTile
          label="审批超时"
          value={fmtInt(data.approval_timeouts)}
          tone={data.approval_timeouts === 0 ? "success" : "warning"}
        />
      </div>

      {approvalTotal > 0 && (
        <p className="mb-4 text-muted-foreground text-xs">
          审批异常合计 {fmtInt(approvalTotal)}（拒绝 + 超时）
        </p>
      )}

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
        <MetricTile
          label="委派计划"
          value={fmtInt(data.delegate_plans)}
          tone="neutral"
        />
        <MetricTile
          label="审计采集丢失"
          value={fmtInt(data.audit_drops)}
          tone={data.audit_drops === 0 ? "success" : "warning"}
        />
      </div>
    </section>
  );
}

function MetricTile({
  label,
  value,
  tone,
}: {
  label: string;
  value: string;
  tone: "success" | "warning" | "destructive" | "neutral";
}) {
  return (
    <div className="rounded-xl border border-border bg-muted/30 p-4">
      <div className="text-muted-foreground text-sm">{label}</div>
      <div
        className={cn(
          "mt-1 text-2xl font-semibold tabular-nums",
          tone === "destructive"
            ? "text-destructive"
            : tone === "warning"
              ? "text-warning"
              : tone === "success"
                ? "text-foreground"
                : "text-foreground",
        )}
      >
        {value}
      </div>
    </div>
  );
}
