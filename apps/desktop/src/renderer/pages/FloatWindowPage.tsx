import { useFloatWindowProjectionConsumer } from "@/components/layout/DesktopFloatWindowBridge";
import {
  SidePanelSurfaceBody,
  sidePanelFloatTitle,
} from "@/components/layout/SidePanelSurfaceBody";
import { WindowControls } from "@/components/layout/WindowControls";
import { isMac, macTitleBarInsetClass } from "@/lib/platform";
import { useApplyTheme } from "@/lib/theme";
import { useConversationStore } from "@/stores/conversation";
import {
  CHANGES_TAB_ID,
  WORKSPACE_TAB_ID,
  type DetailTab,
  useSidePanelStore,
} from "@/stores/sidePanel";
import { PanelsTopLeft } from "lucide-react";
import { useEffect } from "react";
import { useSearchParams } from "react-router-dom";

/**
 * Thin OS-window shell for方案 C（UX §十 · 真 OS 窗）.
 * Hash: `#/float?cid=…&tab=…` — body reuses {@link SidePanelSurfaceBody};
 * projection state arrives via BroadcastChannel from the main window (SSE authority).
 *
 * Chrome = title + {@link WindowControls}（无最小化；关闭=钉回主坞）。
 * **否决**钉回/自定义关闭、真窗最小化（Win owned + frameless 无法做好）。
 */
export function FloatWindowPage() {
  useApplyTheme();

  const [params] = useSearchParams();
  const conversationId = params.get("cid")?.trim() || "";
  const tabId = params.get("tab")?.trim() || "";

  useEffect(() => {
    if (!conversationId) return;
    useConversationStore.getState().setCurrentConversation(conversationId);
  }, [conversationId]);

  useFloatWindowProjectionConsumer(conversationId, tabId);

  const tabs = useSidePanelStore((s) => s.tabs);
  const title = tabId ? sidePanelFloatTitle(tabId, tabs) : "浮窗";
  const ready = Boolean(tabId) && hasFloatTabData(tabId, tabs);

  return (
    <div
      data-testid="float-window-page"
      data-cid={conversationId || undefined}
      data-tab={tabId || undefined}
      className="flex h-screen w-screen flex-col overflow-hidden bg-background"
    >
      <header
        className={`flex h-10 shrink-0 items-center border-b border-border bg-card px-2 [-webkit-app-region:drag] ${
          isMac ? macTitleBarInsetClass : ""
        }`}
      >
        <div className="min-w-0 flex-1 truncate px-1 text-sm font-medium text-foreground">
          {title}
        </div>
        <div className="flex items-center gap-0.5 [-webkit-app-region:no-drag]">
          <WindowControls showMinimize={false} />
        </div>
      </header>

      <main className="relative min-h-0 flex-1 overflow-hidden">
        {ready ? (
          <SidePanelSurfaceBody tabId={tabId} showApprovals />
        ) : (
          <FloatWindowEmptyState
            missingParams={!tabId}
            conversationId={conversationId}
          />
        )}
      </main>
    </div>
  );
}

/** Workspace / changes need no tab row; content tabs require store data (sync). */
export function hasFloatTabData(
  tabId: string,
  tabs: readonly DetailTab[],
): boolean {
  if (tabId === WORKSPACE_TAB_ID || tabId === CHANGES_TAB_ID) return true;
  return tabs.some((t) => t.id === tabId);
}

function FloatWindowEmptyState({
  missingParams,
  conversationId,
}: {
  missingParams: boolean;
  conversationId: string;
}) {
  return (
    <div
      data-testid="float-window-empty"
      className="flex h-full flex-col items-center justify-center gap-2 px-6 text-center"
    >
      <PanelsTopLeft size={26} className="text-muted-foreground/40" />
      <p className="text-sm text-muted-foreground">
        {missingParams ? "缺少浮窗参数" : "面板数据尚未同步"}
      </p>
      <p className="text-xs text-muted-foreground">
        {missingParams
          ? "需要 #/float?cid=…&tab=… 才能打开对应面板。"
          : conversationId
            ? "正在从主窗同步面板数据…"
            : "缺少对话 id（cid）；无法同步投影态。"}
      </p>
    </div>
  );
}
