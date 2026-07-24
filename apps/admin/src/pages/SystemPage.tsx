import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Spinner } from "@/components/ui/Spinner";
import { cn, fmtCompact, fmtInt, nanoUsdToUsd } from "@/lib/utils";
import {
  clientGitSha,
  clientVersion,
  formatGitSha,
} from "@/lib/clientBuildInfo";
import { errorMessage } from "@/services/api";
import {
  type AdminSystemStatus,
  fetchSystemStatus,
} from "@/services/adminSystem";
import {
  fetchReleaseDrift,
  type ReleaseDriftSnapshot,
  versionsMatch,
} from "@/services/releaseDrift";
import { RefreshCw } from "lucide-react";
import { type ReactNode, useCallback, useEffect, useState } from "react";

function orUnknown(s: string): string {
  return !s || s === "unknown" ? "未知" : s;
}

function quotaLimit(value: string): ReactNode {
  return value === "0" ? <span className="text-muted-foreground">不限</span> : value;
}

export function SystemPage() {
  const [data, setData] = useState<AdminSystemStatus | null>(null);
  const [drift, setDrift] = useState<ReleaseDriftSnapshot | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const [system, releaseDrift] = await Promise.all([
        fetchSystemStatus(),
        fetchReleaseDrift(),
      ]);
      setData(system);
      setDrift(releaseDrift);
    } catch (err) {
      setError(errorMessage(err));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    void load();
  }, [load]);

  return (
    <div className="mx-auto max-w-[1200px] px-6 py-8">
      <div className="mb-6 flex items-center justify-between gap-4">
        <div>
          <h1 className="text-xl font-semibold text-foreground">系统状态</h1>
          <p className="mt-1 text-sm text-muted-foreground">
            只读部署快照 · 计费模式、全局配额、数据库健康、版本
          </p>
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
        <>
          {data.admins <= 1 && data.users_total <= 2 && (
            <div className="mb-5 rounded-xl border border-warning/30 bg-warning/10 px-5 py-4 text-sm">
              <p className="font-medium text-foreground">首次部署引导</p>
              <p className="mt-1 text-muted-foreground">
                全新环境请在服务器上运行{" "}
                <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">
                  uv run python scripts/create_admin.py &lt;username&gt;
                </code>{" "}
                （在 <code className="font-mono text-xs">apps/server</code>{" "}
                目录）创建首个管理员；普通用户可直接注册（紧急关闸见环境变量{" "}
                <code className="rounded bg-muted px-1 py-0.5 font-mono text-xs">
                  REGISTRATION_OPEN
                </code>
                ）。
              </p>
            </div>
          )}
          <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          <Card title="计费模式">
            <Badge tone="primary">
              {data.billing_mode === "byok" ? "BYOK · 自带 Key" : "平台付费"}
            </Badge>
            <p className="mt-3 text-muted-foreground text-xs">
              {data.billing_mode === "byok"
                ? "对话跑在用户自带的 DeepSeek Key 上，配额防线休眠。"
                : "平台全局 Key + 配额防线生效。"}
            </p>
          </Card>

          <Card title="数据库">
            <Badge tone={data.database_ok ? "success" : "destructive"}>
              {data.database_ok ? "正常" : "不可达"}
            </Badge>
            <p className="mt-3 text-muted-foreground text-xs">
              实时探测（SELECT 1），与 /readyz 同源。
            </p>
          </Card>

          <Card title="汇率">
            <div className="text-lg font-semibold text-foreground tabular-nums">
              1 USD = ¥{data.cny_per_usd.toFixed(2)}
            </div>
            <p className="mt-3 text-muted-foreground text-xs">
              单一来源，仅用于展示层换算。
            </p>
          </Card>

          <Card title="版本">
            <Row label="控制台版本">{clientVersion()}</Row>
            <Row label="控制台构建">{formatGitSha(clientGitSha())}</Row>
            <Row label="API 版本">{orUnknown(data.version)}</Row>
            <Row label="API 构建">{orUnknown(data.git_sha).slice(0, 12)}</Row>
            <Row label="API 构建时间">{orUnknown(data.built_at)}</Row>
          </Card>

          {drift && (
            <Card title="发布漂移">
              <Row label="Desktop 最新">
                {drift.desktopGithubVersion ?? "—"}
                {drift.desktopGithubTag ? (
                  <span className="ml-2 text-muted-foreground text-xs">
                    ({drift.desktopGithubTag})
                  </span>
                ) : null}
              </Row>
              <Row label="下载页展示">
                {drift.websiteDownloadVersion ?? "—"}
              </Row>
              <Row label="GitHub ↔ 下载页">
                <DriftBadge
                  ok={versionsMatch(
                    drift.desktopGithubVersion,
                    drift.websiteDownloadVersion,
                  )}
                  okLabel="一致"
                  warnLabel="不一致"
                  unknownLabel="未知"
                />
              </Row>
              <Row label="控制台 ↔ API SHA">
                <DriftBadge
                  ok={
                    data.git_sha && clientGitSha() !== "unknown"
                      ? data.git_sha.startsWith(clientGitSha()) ||
                        clientGitSha().startsWith(data.git_sha.slice(0, 7))
                      : null
                  }
                  okLabel="同部署"
                  warnLabel="异轨"
                  unknownLabel="未知"
                />
              </Row>
              {drift.errors.length > 0 && (
                <p className="mt-3 text-destructive text-xs">{drift.errors.join(" · ")}</p>
              )}
              <p className="mt-3 text-muted-foreground text-xs">
                Desktop 来自 GitHub Latest；下载页来自官网 runtime API。API 与 Web
                客户端独立部署，SHA 不同属预期。
              </p>
            </Card>
          )}

          <Card title="全局配额默认值">
            <Row label="日 token">
              {quotaLimit(
                data.quota.daily_tokens === 0
                  ? "0"
                  : fmtCompact(data.quota.daily_tokens),
              )}
            </Row>
            <Row label="月成本">
              {quotaLimit(
                data.quota.monthly_cost_nano === 0
                  ? "0"
                  : `$${nanoUsdToUsd(data.quota.monthly_cost_nano).toFixed(2)}`,
              )}
            </Row>
            <Row label="日成本">
              {quotaLimit(
                data.quota.daily_cost_nano === 0
                  ? "0"
                  : `$${nanoUsdToUsd(data.quota.daily_cost_nano).toFixed(2)}`,
              )}
            </Row>
            <Row label="日请求">
              {quotaLimit(
                data.quota.daily_requests === 0
                  ? "0"
                  : fmtInt(data.quota.daily_requests),
              )}
            </Row>
            <p className="mt-3 text-muted-foreground text-xs">
              0 = 不限 · 每用户可在「用户管理」覆盖。
            </p>
          </Card>

          <Card title="账号">
            <Row label="总数">{fmtInt(data.users_total)}</Row>
            <Row label="活跃">{fmtInt(data.users_active)}</Row>
            <Row label="管理员">{fmtInt(data.admins)}</Row>
          </Card>
        </div>
        </>
      )}
    </div>
  );
}

function Card({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="rounded-xl border border-border bg-card p-5">
      <h2 className="mb-3 text-sm font-medium text-muted-foreground">{title}</h2>
      {children}
    </div>
  );
}

function Row({ label, children }: { label: string; children: ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 py-1.5 text-sm">
      <span className="text-muted-foreground">{label}</span>
      <span className="font-medium text-foreground tabular-nums">{children}</span>
    </div>
  );
}

function DriftBadge({
  ok,
  okLabel,
  warnLabel,
  unknownLabel,
}: {
  ok: boolean | null;
  okLabel: string;
  warnLabel: string;
  unknownLabel: string;
}) {
  if (ok === null) {
    return <Badge tone="neutral">{unknownLabel}</Badge>;
  }
  return <Badge tone={ok ? "success" : "warning"}>{ok ? okLabel : warnLabel}</Badge>;
}
