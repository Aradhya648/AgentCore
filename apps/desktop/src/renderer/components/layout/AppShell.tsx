import { useGroupedConversations } from "@/hooks/useConversations";
import { isWebClient } from "@/lib/capabilities";
import { GLOBAL_SHORTCUTS, shouldRunGlobalShortcut } from "@/lib/shortcuts";
import { useApplyTheme } from "@/lib/theme";
import { startRealtime, stopRealtime } from "@/services/realtime";
import { startServerHealthMonitor } from "@/services/serverHealth";
import {
  startNativeNotificationRouting,
  startTeamActivityNotifications,
} from "@/services/teamActivityNotifications";
import { useStandingInboxStore } from "@/stores/standingInbox";
import { startUpdates } from "@/stores/updates";
import { useUsageStore } from "@/stores/usage";
import { useEffect, useRef } from "react";
import { Outlet, useLocation, useNavigate } from "react-router-dom";
import { ShareConversationDialog } from "../conversation/ShareConversationDialog";
import { CreateFolderMenuHost } from "../folders/CreateFolderMenu";
import { Sidebar } from "../sidebar/Sidebar";
import { CommandPalette } from "./CommandPalette";
import { OutdatedClientBanner } from "./OutdatedClientBanner";
import { TitleBar } from "./TitleBar";

export function AppShell() {
  // Apply the persisted theme to the DOM and keep it in sync with the OS while
  // set to 跟随系统 (the store only holds the value; this is its sole applier).
  useApplyTheme();

  // Warm the grouped query (folders + conversations) at the shell on mount so
  // the sidebar list is ready before it renders — even if the sidebar starts
  // collapsed, the route hasn't mounted a list yet, etc. React Query owns both
  // halves now (folders via useFolders, conversations via useConversations), so
  // there's no store to hydrate here; this call only kicks off the shared fetch.
  useGroupedConversations();

  // Load the account usage summary once on mount so the FX rate (cnyPerUsd) every
  // cost row formats with is the authoritative server value, not the default
  // fallback. Best-effort: the store keeps the default rate on failure.
  useEffect(() => {
    void useUsageStore.getState().fetchSummary();
  }, []);

  // Open the per-user realtime firehose for the whole authenticated session
  // (消息IM.md §四). It lives at the shell — not the 消息 page — so unread badges
  // and incoming messages update even while the user is elsewhere; it
  // self-manages 401→refresh→reconnect and re-syncs on each (re)connect.
  useEffect(() => {
    startRealtime();
    return () => stopRealtime();
  }, []);

  // Standing-task inbox badge (awaiting_user + unacked failed) — soft-poll so
  // More → 收件箱 stays live even when the user is elsewhere.
  useEffect(() => {
    if (typeof window !== "undefined" && window.__WEB_PREVIEW__) return;
    return useStandingInboxStore.getState().startPolling();
  }, []);

  // Ambient backend-connectivity heartbeat (probes /readyz) so the composer can
  // show whether the server is reachable *before* the user sends — offline preview
  // has no backend, so skip it there. Lives at the shell so it spans the whole
  // authenticated session regardless of route.
  useEffect(() => {
    if (typeof window !== "undefined" && window.__WEB_PREVIEW__) return;
    return startServerHealthMonitor();
  }, []);

  // Auto-update lives at the shell so a downloaded build surfaces its "重启安装"
  // notice (and the 关于 page status stays live) regardless of the current route.
  // The main process drives the silent download + check schedule; this only mirrors
  // status and toasts when an update is ready (前端技术与架构.md §7.6).
  useEffect(() => startUpdates(), []);

  // 跨对话完成通知 (前端UX设计.md §一 全局协作感知): ambient, read-only subscription so a team
  // finishing / failing / needing approval in a conversation the user isn't viewing
  // surfaces a toast with a one-click jump. Lives at the shell so it spans every route.
  useEffect(() => {
    const stopActivity = startTeamActivityNotifications();
    const stopNativeRouting = startNativeNotificationRouting();
    return () => {
      stopActivity();
      stopNativeRouting();
    };
  }, []);

  // Global keyboard shortcuts (§二) — dispatched off the single-source table in
  // lib/shortcuts.ts (also rendered by the 快捷键 settings page, so behavior and
  // the documented chord never drift). Chords yield to editable focus (input /
  // textarea / contenteditable) except Cmd/Ctrl+K command palette; navigate is
  // read via a ref so the effect needn't resubscribe on every route change.
  const navigate = useNavigate();
  const navigateRef = useRef(navigate);
  navigateRef.current = navigate;

  // The offline preview (#/preview) is a full-window dev surface with its own
  // scenario navigator, so the app's conversation sidebar is pure chrome there.
  // Hide it (the TitleBar stays) to give every replayed AI state — the canvas
  // view especially — the full window width.
  const { pathname } = useLocation();
  const hideSidebar =
    pathname === "/preview" ||
    pathname.startsWith("/preview/") ||
    pathname.startsWith("/simulation");

  // 生产 web 客户端不画桌面窗口顶栏（浏览器自带窗口 chrome）——品牌/折叠/搜索改由侧栏顶部
  // 承载（见 Sidebar）。桌面 Electron 外壳与离线预览 #/preview 仍保留顶栏。
  const webClient = isWebClient();
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (!(e.ctrlKey || e.metaKey) || e.altKey) return;
      const key = e.key.toLowerCase();
      const match = GLOBAL_SHORTCUTS.find((s) => s.keys.includes(key));
      if (!match) return;
      if (!shouldRunGlobalShortcut(match.id, e.target)) return;
      e.preventDefault();
      match.run(navigateRef.current);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, []);

  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden">
      {!webClient && <TitleBar />}
      <OutdatedClientBanner />

      <div className="flex min-h-0 flex-1 overflow-hidden">
        {!hideSidebar && <Sidebar />}
        <main className="relative flex min-h-0 flex-1 overflow-hidden">
          <Outlet />
        </main>
      </div>

      <CommandPalette />
      <ShareConversationDialog />
      <CreateFolderMenuHost />
    </div>
  );
}
