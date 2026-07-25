import { type VersionInfo, fetchVersion } from "@/api/system";
import {
  checkAndroidUpdate,
  openAndroidDownload,
  useAndroidUpdates,
} from "@/lib/androidUpdates";
import {
  clientGitSha,
  clientPlatform,
  clientVersion,
  formatGitSha,
} from "@/lib/clientBuildInfo";
import { Capacitor } from "@capacitor/core";
// 关于 (/more/about) — version + build provenance + Android sideload soft update.
import { useEffect, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import "@/pages/more/more.css";

function AndroidUpdateSection() {
  const { phase, availableVersion, downloadUrl, message } = useAndroidUpdates();
  const busy = phase === "checking";
  const canDownload = phase === "available" && Boolean(downloadUrl);

  let statusText = message ?? "点击下方按钮检查是否有新版本。";
  if (phase === "idle") {
    statusText = "点击下方按钮检查是否有新版本。";
  } else if (phase === "unsupported") {
    statusText = message ?? "当前环境不检查更新。";
  } else if (phase === "checking") {
    statusText = "正在检查更新…";
  } else if (phase === "available" && availableVersion) {
    statusText = `发现新版本 ${availableVersion}。点击「去下载」在浏览器中获取 APK。`;
  } else if (phase === "current") {
    statusText = message ?? "已是最新版本。";
  } else if (phase === "error") {
    statusText = message ?? "检查更新失败。";
  }

  return (
    <section className="settings-section">
      <h2 className="settings-section-title">软件更新</h2>
      <p className="settings-desc">{statusText}</p>
      <div className="btn-row">
        {canDownload ? (
          <button type="button" onClick={() => openAndroidDownload()}>
            去下载
          </button>
        ) : (
          <button
            type="button"
            className="btn-outline"
            disabled={busy || phase === "unsupported"}
            onClick={() => void checkAndroidUpdate()}
          >
            {busy ? "检查中…" : "检查更新"}
          </button>
        )}
      </div>
    </section>
  );
}

export function AboutSettings() {
  const navigate = useNavigate();
  const [info, setInfo] = useState<VersionInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const showAndroidUpdate =
    Capacitor.isNativePlatform() && Capacitor.getPlatform() === "android";

  useEffect(() => {
    let cancelled = false;
    fetchVersion()
      .then((data) => !cancelled && setInfo(data))
      .catch(() => !cancelled && setError("获取版本信息失败"))
      .finally(() => !cancelled && setLoading(false));
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="screen">
      <header className="bar">
        <button
          type="button"
          className="link"
          onClick={() => navigate("/more")}
        >
          ← 设置
        </button>
        <span>关于 AgentCore</span>
        <span style={{ width: 44 }} />
      </header>

      <div className="settings-body">
        <p className="settings-desc">版本信息与构建溯源。</p>
        {loading ? (
          <p className="muted hint">加载中…</p>
        ) : error ? (
          <p className="error hint">{error}</p>
        ) : info ? (
          <>
            <Row label="客户端版本" value={clientVersion()} />
            <Row label="客户端平台" value={clientPlatform()} />
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

        {showAndroidUpdate ? <AndroidUpdateSection /> : null}

        <section className="settings-section">
          <h2 className="settings-section-title">法律与合规</h2>
          <p className="settings-desc">用户协议与隐私政策。</p>
          <div className="legal-links">
            <Link to="/legal/terms">用户协议</Link>
            <Link to="/legal/privacy">隐私政策</Link>
          </div>
        </section>
      </div>
    </div>
  );
}

function Row({
  label,
  value,
  mono,
}: { label: string; value: string; mono?: boolean }) {
  return (
    <div className="about-row">
      <span className="about-label">{label}</span>
      <span className={`about-value${mono ? " mono" : ""}`}>{value}</span>
    </div>
  );
}
