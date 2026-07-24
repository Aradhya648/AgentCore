import { bootstrapAuth } from "@/api/auth";
import { getTokens } from "@/api/client";
import { PushBridge } from "@/components/PushBridge";
import { TabLayout } from "@/components/TabLayout";
import { ChatPage } from "@/pages/ChatPage";
import { FilesPage } from "@/pages/FilesPage";
import { LoginPage } from "@/pages/LoginPage";
import { MemoryPage } from "@/pages/MemoryPage";
import { MessagesPage } from "@/pages/MessagesPage";
import { MorePage } from "@/pages/MorePage";
import { PreviewPage } from "@/pages/PreviewPage";
import { ServiceUnavailablePage } from "@/pages/ServiceUnavailablePage";
import { WorkspaceFilesPage } from "@/pages/WorkspaceFilesPage";
import { WorkspacesPage } from "@/pages/WorkspacesPage";
import { ChatThreadPage } from "@/pages/im/ChatThreadPage";
import { NewDmPage } from "@/pages/im/NewDmPage";
import { LegalDocPage } from "@/pages/legal/LegalDocPage";
import { AboutSettings } from "@/pages/more/AboutSettings";
import { AccountSettings } from "@/pages/more/AccountSettings";
import { AutonomySettings } from "@/pages/more/AutonomySettings";
import { ModelSettings } from "@/pages/more/ModelSettings";
import { UsageSettings } from "@/pages/more/UsageSettings";
import { type ReactNode, useCallback, useEffect, useState } from "react";
import { Navigate, Route, Routes, useLocation } from "react-router-dom";

function RequireAuth({ children }: { children: ReactNode }) {
  return getTokens() ? <>{children}</> : <Navigate to="/login" replace />;
}

// A top-level destination: authed + wrapped in the persistent bottom TabBar. The 对话 chat is
// now a tabbed destination too (开盖即聊 — `/` is a draft, `/c/:id` an open conversation; both
// keep the bar, history lives in the chat's ☰ drawer). Detail pages (设置子页 / IM 线程 /
// 单会话文件) use bare RequireAuth so they push full-screen over the bar (底部 4-tab 导航).
function Tabbed({ children }: { children: ReactNode }) {
  return (
    <RequireAuth>
      <TabLayout>{children}</TabLayout>
    </RequireAuth>
  );
}

function Splash() {
  return (
    <div className="screen center">
      <p className="muted">正在启动…</p>
    </div>
  );
}

type GateState =
  | { phase: "loading" }
  | { phase: "ready" } // authenticated or logged-out — RequireAuth picks the route
  | { phase: "unavailable"; reason: string };

export function App() {
  const location = useLocation();
  const previewDev = import.meta.env.DEV && location.pathname === "/preview";

  if (previewDev) {
    return (
      <>
        <PushBridge />
        <Routes>
          <Route path="/preview" element={<PreviewPage />} />
        </Routes>
      </>
    );
  }

  return <AppShell />;
}

function AppShell() {
  // Resolve auth before routing so RequireAuth's synchronous token check sees a
  // trustworthy state. An `unavailable` result drives a retry screen instead of a
  // login form / erroring chat page while the backend is down (mirrors desktop).
  const [state, setState] = useState<GateState>({ phase: "loading" });

  const run = useCallback((force = false) => {
    setState({ phase: "loading" });
    void bootstrapAuth(force).then((r) =>
      setState(
        r.kind === "unavailable"
          ? { phase: "unavailable", reason: r.reason }
          : { phase: "ready" },
      ),
    );
  }, []);

  useEffect(() => {
    run();
  }, [run]);

  // PushBridge mounts the native push listeners (tap → deep-link); it lives outside the gate
  // so it's present even during the loading splash, catching a cold-start notification tap.
  const content =
    state.phase === "loading" ? (
      <Splash />
    ) : state.phase === "unavailable" ? (
      <ServiceUnavailablePage reason={state.reason} onRetry={() => run(true)} />
    ) : (
      <Routes>
        <Route path="/login" element={<LoginPage />} />
        <Route path="/legal/:docId" element={<LegalDocPage />} />
        <Route
          path="/"
          element={
            <Tabbed>
              <ChatPage />
            </Tabbed>
          }
        />
        <Route
          path="/c/:id"
          element={
            <Tabbed>
              <ChatPage />
            </Tabbed>
          }
        />
        <Route
          path="/c/:id/files"
          element={
            <RequireAuth>
              <FilesPage />
            </RequireAuth>
          }
        />
        <Route
          path="/files"
          element={
            <Tabbed>
              <WorkspacesPage />
            </Tabbed>
          }
        />
        <Route
          path="/files/:wsId"
          element={
            <Tabbed>
              <WorkspaceFilesPage />
            </Tabbed>
          }
        />
        <Route
          path="/memory"
          element={
            <RequireAuth>
              <MemoryPage />
            </RequireAuth>
          }
        />
        <Route
          path="/more"
          element={
            <Tabbed>
              <MorePage />
            </Tabbed>
          }
        />
        <Route
          path="/more/model"
          element={
            <RequireAuth>
              <ModelSettings />
            </RequireAuth>
          }
        />
        <Route
          path="/more/autonomy"
          element={
            <RequireAuth>
              <AutonomySettings />
            </RequireAuth>
          }
        />
        <Route
          path="/more/account"
          element={
            <RequireAuth>
              <AccountSettings />
            </RequireAuth>
          }
        />
        <Route
          path="/more/usage"
          element={
            <RequireAuth>
              <UsageSettings />
            </RequireAuth>
          }
        />
        <Route
          path="/more/about"
          element={
            <RequireAuth>
              <AboutSettings />
            </RequireAuth>
          }
        />
        <Route
          path="/im"
          element={
            <Tabbed>
              <MessagesPage />
            </Tabbed>
          }
        />
        <Route
          path="/im/new"
          element={
            <RequireAuth>
              <NewDmPage />
            </RequireAuth>
          }
        />
        <Route
          path="/im/c/:chatId"
          element={
            <RequireAuth>
              <ChatThreadPage />
            </RequireAuth>
          }
        />
        <Route path="*" element={<Navigate to="/" replace />} />
      </Routes>
    );

  return (
    <>
      <PushBridge />
      {content}
    </>
  );
}
