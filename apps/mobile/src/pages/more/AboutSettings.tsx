import { type VersionInfo, fetchVersion } from "@/api/system";
import {
  clientGitSha,
  clientVersion,
  formatGitSha,
} from "@/lib/clientBuildInfo";
// 关于 (/more/about) — version + build provenance. The desktop's 软件更新 section is
// dropped (mobile updates ship through the App Store / Play, not an in-app updater).
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import "@/pages/more/more.css";

export function AboutSettings() {
  const navigate = useNavigate();
  const [info, setInfo] = useState<VersionInfo | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

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
