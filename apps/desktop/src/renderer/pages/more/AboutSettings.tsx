import { BrandMark } from "@/components/brand/BrandMark";
import { Button } from "@/components/ui";
import { Switch } from "@/components/ui/Switch";
import { hasAutoUpdater } from "@/lib/capabilities";
import {
  clientGitSha,
  clientVersion,
  formatGitSha,
} from "@/lib/clientBuildInfo";
import { formatDownloadProgress } from "@/lib/format";
import { APP_PATHS } from "@/pages/toolbox/manual/paths";
import { type VersionInfo, fetchVersion } from "@/services/system";
import { useUIStore } from "@/stores/ui";
import { useUpdatesStore } from "@/stores/updates";
import type { UpdaterStatus } from "@shared/updater-contract";
import { Loader2, RefreshCw } from "lucide-react";
import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { SettingsHeader } from "./SettingsHeader";

function Row({
  label,
  value,
  mono,
}: {
  label: string;
  value: string;
  mono?: boolean;
}) {
  return (
    <p className="flex gap-2">
      <span className="w-20 shrink-0 text-muted-foreground">{label}</span>
      <span className={mono ? "font-mono text-foreground" : "text-foreground"}>
        {value}
      </span>
    </p>
  );
}

/** Human-readable line for each updater phase (发布与门禁.md §7.6). */
function updateStatusText(status: UpdaterStatus): string {
  switch (status.phase) {
    case "idle":
      return "点击下方按钮检查是否有新版本。";
    case "unsupported":
      return "开发模式下不检查更新；自动更新仅在安装版中生效。";
    case "checking":
      return "正在检查更新…";
    case "not-available":
      return "已是最新版本。";
    case "available":
      return `发现新版本 ${status.version}，确认后开始下载。`;
    case "downloading":
      return `正在下载新版本 ${status.version}…（${formatDownloadProgress({
        percent: status.percent,
        transferred: status.transferred,
        total: status.total,
        bytesPerSecond: status.bytesPerSecond,
      })}）`;
    case "downloaded":
      return `新版本 ${status.version} 已下载，重启后生效。`;
    case "error":
      return `更新检查失败：${status.message}`;
  }
}

/** 软件更新: mirror the main-process updater status + 检查 / 查看 / 重启安装. */
function UpdateSection() {
  const status = useUpdatesStore((s) => s.status);
  const check = useUpdatesStore((s) => s.check);
  const install = useUpdatesStore((s) => s.install);
  const openUpdateDialog = useUpdatesStore((s) => s.openUpdateDialog);

  const busy = status.phase === "checking" || status.phase === "downloading";

  return (
    <section className="mt-8 border-t border-border pt-6">
      <h2 className="text-sm font-semibold text-foreground">软件更新</h2>
      <p className="mt-1 text-xs text-muted-foreground">
        {updateStatusText(status)}
      </p>
      <div className="mt-3 flex flex-wrap gap-2">
        {status.phase === "downloaded" ? (
          <Button size="md" onClick={() => void install()}>
            重启安装
          </Button>
        ) : status.phase === "available" || status.phase === "downloading" ? (
          <Button size="md" onClick={() => openUpdateDialog()}>
            {status.phase === "downloading" ? "查看下载进度" : "查看更新"}
          </Button>
        ) : (
          <Button
            variant="neutral"
            size="md"
            disabled={busy || status.phase === "unsupported"}
            icon={
              busy ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <RefreshCw size={14} />
              )
            }
            onClick={() => void check()}
          >
            检查更新
          </Button>
        )}
        {status.phase === "available" || status.phase === "downloading" ? (
          <Button
            variant="neutral"
            size="md"
            disabled={busy}
            icon={
              busy ? (
                <Loader2 size={14} className="animate-spin" />
              ) : (
                <RefreshCw size={14} />
              )
            }
            onClick={() => void check()}
          >
            重新检查
          </Button>
        ) : null}
      </div>
    </section>
  );
}

/**
 * 开发者 / 诊断模式 (前端UX设计.md §十) — advanced, off-by-default toggle that
 * surfaces low-level execution diagnostics in run detail (裸 run / trace ids、
 * 调度埋点等)。报障出口（错误卡 / 气泡「更多」→「复制排查包」）不依赖本开关。
 * Lives on 关于 — next to build 溯源 — so this stays off 大众-facing 偏好 pages.
 */
function DiagnosticModeSection() {
  const diagnosticMode = useUIStore((s) => s.diagnosticMode);
  const setDiagnosticMode = useUIStore((s) => s.setDiagnosticMode);

  return (
    <section className="mt-8 border-t border-border pt-6">
      <div className="flex items-center justify-between gap-4">
        <div className="min-w-0">
          <h2 className="text-sm font-semibold text-foreground">
            开发者 / 诊断模式
          </h2>
          <p className="mt-1 text-xs text-muted-foreground">
            在运行详情里显示运行 / 追踪
            ID、调度埋点等底层信息。普通使用无需开启；报障请用错误卡或消息「更多」里的「复制排查包」（无需开本开关）。
          </p>
        </div>
        <Switch
          checked={diagnosticMode}
          onCheckedChange={setDiagnosticMode}
          label="开发者 / 诊断模式"
        />
      </div>
    </section>
  );
}

export function AboutSettings() {
  const [info, setInfo] = useState<VersionInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const data = await fetchVersion();
        if (!cancelled) setInfo(data);
      } catch {
        if (!cancelled) setError("获取版本信息失败");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div>
      <div className="mb-8">
        <BrandMark size="md" className="text-foreground" />
        <p className="mt-4 text-base font-medium text-foreground">
          协作，是更高级的智能。
        </p>
        <p className="mt-1 text-sm text-muted-foreground">协作智能平台</p>
      </div>

      <SettingsHeader
        title="关于 AgentCore"
        description="版本信息与构建溯源。"
      />

      <div className="mt-6 space-y-2 text-sm">
        {loading ? (
          <p className="text-muted-foreground">加载中…</p>
        ) : error ? (
          <p className="text-destructive">{error}</p>
        ) : info ? (
          <>
            <Row label="客户端版本" value={clientVersion()} />
            <Row
              label="客户端构建"
              value={formatGitSha(clientGitSha())}
              mono={clientGitSha() !== "unknown"}
            />
            <Row label="API 版本" value={info.version} />
            <Row
              label="API 构建"
              value={formatGitSha(info.gitSha)}
              mono={info.gitSha !== "unknown"}
            />
            <Row
              label="API 构建时间"
              value={info.builtAt === "unknown" ? "—" : info.builtAt}
            />
          </>
        ) : null}
      </div>

      {/* 自动更新仅桌面外壳；web 客户端随刷新拿到新版，故 web 不挂「软件更新」。 */}
      {hasAutoUpdater() && <UpdateSection />}

      <section className="mt-8 border-t border-border pt-6">
        <h2 className="text-sm font-semibold text-foreground">法律与合规</h2>
        <p className="mt-1 text-xs text-muted-foreground">
          用户协议与隐私政策。
        </p>
        <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-sm">
          <Link
            to={APP_PATHS.more.legal.terms}
            className="text-foreground underline-offset-2 hover:underline"
          >
            用户协议
          </Link>
          <Link
            to={APP_PATHS.more.legal.privacy}
            className="text-foreground underline-offset-2 hover:underline"
          >
            隐私政策
          </Link>
        </div>
      </section>

      <DiagnosticModeSection />
    </div>
  );
}
