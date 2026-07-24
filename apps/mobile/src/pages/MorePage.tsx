import { type User, logout, me } from "@/api/auth";
import { getTokens } from "@/api/client";
import { Avatar } from "@/pages/more/Avatar";
// Settings hub (设置/更多) — mobile's home for account/model/autonomy/usage/about.
//
// Desktop has a left-nav + content split (MorePage.tsx); mobile is touch-native: a hub
// list of rows that drill into full-screen sub-pages (/more/model · /more/autonomy ·
// /more/account · /more/usage · /more/about). Two desktop sections are dropped by the
// 减法 boundary — 外观 (手机端只浅色、无暗色) and 快捷键 (无物理键盘) — and 成员
// (admin) stays a desktop/admin-web task. There is no global auth store on mobile, so
// identity is fetched here on open (matches the skeleton's per-page fetch convention).
import { useEffect, useState } from "react";
import { useNavigate } from "react-router-dom";
import "@/pages/more/more.css";

export function MorePage() {
  const navigate = useNavigate();
  const [user, setUser] = useState<User | null>(null);

  useEffect(() => {
    let cancelled = false;
    me()
      .then((u) => {
        if (!cancelled) setUser(u);
      })
      .catch(() => {
        // A cleared token → bounce to login (mirrors the other pages' guard).
        if (!getTokens()) navigate("/login", { replace: true });
      });
    return () => {
      cancelled = true;
    };
  }, [navigate]);

  async function onLogout() {
    await logout();
    navigate("/login", { replace: true });
  }

  return (
    <div className="screen">
      <header className="bar">
        <span>我的</span>
      </header>

      <div className="list" style={{ padding: 0 }}>
        <div className="more-ident">
          <Avatar user={user} size={52} />
          <div className="more-ident-text">
            <span className="more-name">
              {user?.display_name || user?.username || "—"}
            </span>
            {user?.username && (
              <span className="more-sub">@{user.username}</span>
            )}
          </div>
        </div>

        <div className="more-group">
          <NavRow label="模型配置" onClick={() => navigate("/more/model")} />
          <NavRow
            label="新会话默认权限"
            onClick={() => navigate("/more/autonomy")}
          />
          <NavRow label="账户设置" onClick={() => navigate("/more/account")} />
          <NavRow label="用量" onClick={() => navigate("/more/usage")} />
          <NavRow label="关于" onClick={() => navigate("/more/about")} />
        </div>

        <div className="more-group">
          <button
            type="button"
            className="more-row more-row-danger"
            onClick={() => void onLogout()}
          >
            <span className="more-row-label">退出登录</span>
          </button>
        </div>
      </div>
    </div>
  );
}

function NavRow({ label, onClick }: { label: string; onClick: () => void }) {
  return (
    <button type="button" className="more-row" onClick={onClick}>
      <span className="more-row-label">{label}</span>
      <span className="more-row-chevron" aria-hidden>
        ›
      </span>
    </button>
  );
}
