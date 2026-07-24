import { type AutonomyPolicy, getAutonomy, setAutonomy } from "@/api/autonomy";
// 自主度 (/more/autonomy) — AutonomyPolicy 三档（安全权限与治理 §三）。
//
// Mirrors desktop AutonomySettings product-wise: three radio options + semantics.
// Mobile is cloud-only (no sidecar), so there is no local autonomyPolicy cache —
// GET/PUT the API directly. Save feedback is inline (手机无 toast 原语).
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import "@/pages/more/more.css";

interface AutonomyOption {
  value: AutonomyPolicy;
  label: string;
  description: string;
}

const OPTIONS: AutonomyOption[] = [
  {
    value: "always_ask",
    label: "只观察",
    description: "新会话默认：不跑代码/终端；写文件逐次审批。",
  },
  {
    value: "first_grant",
    label: "开工授权（推荐）",
    description: "新会话默认：开工卡一次授权本委派所需能力。",
  },
  {
    value: "full_auto",
    label: "完全信任",
    description: "新会话默认：AI 将与你同权执行命令；跳过开工卡。",
  },
];

export function AutonomySettings() {
  const navigate = useNavigate();
  const [policy, setPolicy] = useState<AutonomyPolicy | null>(null);
  const [pending, setPending] = useState(false);
  const [loadError, setLoadError] = useState<string | null>(null);
  const [saveError, setSaveError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    let alive = true;
    getAutonomy()
      .then((d) => {
        if (!alive) return;
        setPolicy(d.policy);
      })
      .catch((e) => {
        if (!alive) return;
        setLoadError(e instanceof Error ? e.message : "加载自主度设置失败");
        setPolicy("first_grant");
      });
    return () => {
      alive = false;
    };
  }, []);

  async function onSelect(next: AutonomyPolicy) {
    if (next === policy || pending) return;
    setPending(true);
    setSaveError(null);
    setSaved(false);
    try {
      const d = await setAutonomy(next);
      setPolicy(d.policy);
      setSaved(true);
    } catch (e) {
      setSaveError(e instanceof Error ? e.message : "设置失败");
    } finally {
      setPending(false);
    }
  }

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
        <span>新会话默认权限</span>
        <span style={{ width: 44 }} />
      </header>

      <div className="settings-body">
        <p className="settings-desc">
          只影响之后新建的对话。已有会话的权限模式在对话详情中查看。
        </p>

        {policy === null && !loadError ? (
          <p className="muted hint">加载中…</p>
        ) : (
          <>
            {loadError && <p className="error hint">{loadError}</p>}
            <div className="choice-list" role="radiogroup" aria-label="自主度">
              {OPTIONS.map((option) => {
                const selected = option.value === policy;
                return (
                  <label
                    key={option.value}
                    className={
                      selected ? "choice-row choice-row-active" : "choice-row"
                    }
                  >
                    <input
                      type="radio"
                      name="autonomy-policy"
                      value={option.value}
                      checked={selected}
                      disabled={pending || policy === null}
                      onChange={() => void onSelect(option.value)}
                      className="choice-radio-input"
                    />
                    <div className="choice-text">
                      <span className="choice-label">{option.label}</span>
                      <span className="choice-desc">{option.description}</span>
                    </div>
                  </label>
                );
              })}
            </div>
            {saveError && <p className="error hint">{saveError}</p>}
            {saved && !saveError && (
              <p className="hint" style={{ color: "var(--success)" }}>
                已更新自主度
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
