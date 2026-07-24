import { MinimalTitleBar } from "@/components/layout/TitleBar";
import { isWebClient } from "@/lib/capabilities";
import { LoginPage } from "@/pages/LoginPage";
import { ServiceUnavailablePage } from "@/pages/ServiceUnavailablePage";
import {
  clearAgentTownSession,
  persistAgentTownSession,
} from "@/services/agentTownSession";
import {
  setServiceUnavailableHandler,
  setSessionRenewedHandler,
  setUnauthorizedHandler,
} from "@/services/api";
import { bootstrapAuth, diagnoseOutage } from "@/services/auth";
import { ensureDefaultContainerRoot } from "@/services/defaultWorkspace";
import { useAuthStore } from "@/stores/auth";
import { type ReactNode, useCallback, useEffect } from "react";

/**
 * Wraps the pre-auth screens (login / loading / 后端不可用) in draggable window chrome.
 * These render outside AppShell — so without this they'd inherit no title bar, leaving a
 * frameless window with no way to move or close it until login succeeds. The web client
 * omits it (the browser provides its own window chrome).
 */
function PreAuthShell({ children }: { children: ReactNode }) {
  return (
    <div className="flex h-screen w-screen flex-col overflow-hidden">
      {!isWebClient() && <MinimalTitleBar />}
      <div className="min-h-0 flex-1">{children}</div>
    </div>
  );
}

/**
 * Gates the whole app behind authentication.
 *
 * On mount it runs {@link bootstrapAuth}, which resolves to authenticated,
 * unauthenticated, or unavailable (backend down), and wires the api-layer 401
 * handler so any later unrecoverable 401 drops straight back to login. Children
 * (the router) only render once authenticated.
 */
export function AuthGate({ children }: { children: ReactNode }) {
  const status = useAuthStore((s) => s.status);
  const reason = useAuthStore((s) => s.reason);

  const runBootstrap = useCallback(async (opts?: { showLoading?: boolean }) => {
    if (opts?.showLoading !== false) {
      useAuthStore.getState().setLoading();
    }
    try {
      const result = await bootstrapAuth();
      const store = useAuthStore.getState();
      switch (result.kind) {
        case "authenticated":
          store.setAuthenticated(result.user);
          void persistAgentTownSession();
          break;
        case "unavailable":
          store.setUnavailable(result.reason);
          break;
        case "unauthenticated":
          void clearAgentTownSession();
          store.setUnauthenticated();
          break;
      }
    } catch (err) {
      console.error("[auth] bootstrap failed", err);
      useAuthStore
        .getState()
        .setUnavailable("无法连接后端：请确认后端服务已启动后重试。");
    }
  }, []);

  useEffect(() => {
    // Offline web preview (pnpm dev:web / scripts/shoot.mjs) has no backend; skip
    // auth bootstrap entirely so #/preview renders fully offline.
    if (typeof window !== "undefined" && window.__WEB_PREVIEW__) return;
    setUnauthorizedHandler(() => {
      void clearAgentTownSession();
      useAuthStore.getState().setUnauthenticated();
    });
    setSessionRenewedHandler(() => void persistAgentTownSession());
    // Mid-session outage: a non-auth call hit a 5xx/network error. Confirm with
    // /readyz before taking over the screen so a one-off endpoint 500 on a
    // healthy backend doesn't blank the app.
    setServiceUnavailableHandler(() => {
      const cur = useAuthStore.getState().status;
      if (cur === "loading" || cur === "unavailable") return;
      void (async () => {
        const reason = await diagnoseOutage();
        if (reason) useAuthStore.getState().setUnavailable(reason);
      })();
    });
    void runBootstrap();
    return () => {
      setUnauthorizedHandler(null);
      setSessionRenewedHandler(null);
      setServiceUnavailableHandler(null);
    };
  }, [runBootstrap]);

  // 认证成功后预热桌面默认本地容器根（§八.7：仅服务显式本机草稿 / 本地项目创建），
  // 摊薄用户点「本机草稿」时的授权等待。非桌面 / 失败时 no-op，不阻断渲染。
  useEffect(() => {
    if (status === "authenticated") void ensureDefaultContainerRoot();
  }, [status]);

  // Dev: backend tasks often restart during parallel server edits; poll bootstrap
  // so the app recovers when port 8000 comes back without a manual retry click.
  useEffect(() => {
    if (status !== "unavailable" || !import.meta.env.DEV) return;
    const id = window.setInterval(
      () => void runBootstrap({ showLoading: false }),
      5000,
    );
    return () => window.clearInterval(id);
  }, [status, runBootstrap]);

  // Offline web preview: render the app without ever gating on auth.
  if (typeof window !== "undefined" && window.__WEB_PREVIEW__) {
    return <>{children}</>;
  }

  if (status === "loading") {
    return (
      <PreAuthShell>
        <div className="flex h-full w-full items-center justify-center bg-background text-sm text-muted-foreground">
          加载中…
        </div>
      </PreAuthShell>
    );
  }

  if (status === "unavailable") {
    return (
      <PreAuthShell>
        <ServiceUnavailablePage
          reason={reason ?? "无法连接后端：请确认后端服务已启动后重试。"}
          onRetry={() => void runBootstrap()}
        />
      </PreAuthShell>
    );
  }

  if (status === "unauthenticated") {
    return (
      <PreAuthShell>
        <LoginPage />
      </PreAuthShell>
    );
  }

  return <>{children}</>;
}
