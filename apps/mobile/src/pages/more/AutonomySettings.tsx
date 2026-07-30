import { type AutonomyPolicy, getAutonomy, setAutonomy } from "@/api/autonomy";
// 权限配方 (/more/autonomy) — AutonomyPolicy 三配方。
//
// Mirrors desktop AutonomySettings: three recipe options. Mobile is cloud-only
// (no sidecar axes badge mid-session yet) — GET/PUT the API directly.
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
    value: "cautious",
    label: "谨慎",
    description: "新会话默认：改文件逐次问；不预授执行；组团卡按规则。",
  },
  {
    value: "less_interrupt",
    label: "少打断（推荐）",
    description:
      "新会话默认：本会话信任改文件；自动执行；跳过组团卡；本机每次确认。",
  },
  {
    value: "managed",
    label: "托管",
    description:
      "新会话默认：本会话信任改文件；自动执行；跳过组团卡；本机会话信任。",
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
        setLoadError(e instanceof Error ? e.message : "加载权限配方失败");
        setPolicy("less_interrupt");
      });
    return () => {
      alive = false;
    };
  }, []);

  async function onSelect(next: AutonomyPolicy) {
    if (next === policy || pending) return;
    // command=auto recipes (少打断 / 托管) share the same confirm.
    if (
      (next === "less_interrupt" || next === "managed") &&
      policy !== "less_interrupt" &&
      policy !== "managed" &&
      !window.confirm("切换到「免审执行」后，AI 将与你同权执行命令。确定？")
    ) {
      return;
    }
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
          只影响之后新建的对话。已有会话的权限在对话详情中查看。
        </p>

        {policy === null && !loadError ? (
          <p className="muted hint">加载中…</p>
        ) : (
          <>
            {loadError && <p className="error hint">{loadError}</p>}
            <div
              className="choice-list"
              role="radiogroup"
              aria-label="权限配方"
            >
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
                已更新默认配方
              </p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
