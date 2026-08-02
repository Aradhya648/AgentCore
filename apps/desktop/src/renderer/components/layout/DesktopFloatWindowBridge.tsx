import {
  canUseOsFloatWindow,
  floatWindowOpen,
  onFloatWindowClosed,
  floatWindowDock,
  floatWindowDestroy,
} from "@/lib/floatWindowApi";
import {
  applyFloatProjectionSnapshot,
  buildFloatProjectionSnapshot,
  isFloatSyncMessage,
  openFloatSyncChannel,
  postFloatSync,
} from "@/lib/floatWindowSync";
import { sidePanelFloatTitle } from "@/components/layout/SidePanelSurfaceBody";
import {
  CHANGES_TAB_ID,
  WORKSPACE_TAB_ID,
  useSidePanelStore,
} from "@/stores/sidePanel";
import { useConversationStore } from "@/stores/conversation";
import { useExecutionStore } from "@/stores/execution";
import { useInteractionStore } from "@/stores/interactions";
import { useEffect, useRef } from "react";

/**
 * Desktop-only bridge: open true OS float windows for Move'd tabs, publish
 * projection snapshots, and fold closed/focus events back into the main store.
 * Web keeps {@link SidePanelFloatHost} in-app floats — this component no-ops.
 */
export function DesktopFloatWindowBridge() {
  const enabled = canUseOsFloatWindow();
  const floats = useSidePanelStore((s) => s.floats);
  const tabs = useSidePanelStore((s) => s.tabs);
  const focusSurface = useSidePanelStore((s) => s.focusSurface);
  const conversationId = useConversationStore((s) => s.currentConversationId);
  const openedRef = useRef(new Set<string>());

  // Open OS windows only for newly Move'd tabs — never re-open/focus the whole
  // set on floats identity changes (zIndex). Re-focusing all windows on every
  // bump caused a dual-float focus ping-pong with BroadcastChannel focus.
  useEffect(() => {
    if (!enabled || !conversationId) return;
    const live = new Set(floats.map((f) => f.tabId));
    for (const id of [...openedRef.current]) {
      if (!live.has(id)) openedRef.current.delete(id);
    }
    for (const f of floats) {
      if (openedRef.current.has(f.tabId)) continue;
      // Optimistic mark so a concurrent floats re-render doesn't double-open.
      openedRef.current.add(f.tabId);
      const title = sidePanelFloatTitle(f.tabId, tabs);
      void floatWindowOpen({
        tabId: f.tabId,
        conversationId,
        title,
      }).then((ok) => {
        if (!ok) openedRef.current.delete(f.tabId);
      });
    }
  }, [enabled, floats, tabs, conversationId]);

  // Re-focus OS window when focusSurface moves to a float (not on zIndex churn).
  const focusFloatTabId =
    focusSurface.type === "float" ? focusSurface.tabId : null;
  useEffect(() => {
    if (!enabled || !conversationId || !focusFloatTabId) return;
    if (!useSidePanelStore.getState().floats.some((f) => f.tabId === focusFloatTabId)) {
      return;
    }
    void floatWindowOpen({
      tabId: focusFloatTabId,
      conversationId,
      title: sidePanelFloatTitle(focusFloatTabId, tabs),
    });
  }, [enabled, focusFloatTabId, conversationId, tabs]);

  // closed → dock / destroyFloat (user/dock → 钉回；destroy → 销毁可关 kind).
  useEffect(() => {
    if (!enabled) return;
    return onFloatWindowClosed(({ tabId, reason }) => {
      openedRef.current.delete(tabId);
      const panel = useSidePanelStore.getState();
      if (reason === "destroy") {
        if (!panel.destroyFloat(tabId)) panel.dockTab(tabId);
        return;
      }
      panel.dockTab(tabId);
    });
  }, [enabled]);

  // Publish snapshots + answer float requests / focus pings.
  useEffect(() => {
    if (!enabled || !conversationId) return;
    const channel = openFloatSyncChannel();
    if (!channel) return;

    let raf = 0;
    const publishAll = () => {
      const cid = useConversationStore.getState().currentConversationId;
      if (!cid) return;
      const floating = useSidePanelStore.getState().floats;
      for (const f of floating) {
        const snapshot = buildFloatProjectionSnapshot(cid, f.tabId);
        postFloatSync(channel, {
          type: "snapshot",
          conversationId: cid,
          tabId: f.tabId,
          snapshot,
        });
      }
    };
    const schedulePublish = () => {
      if (raf) return;
      raf = requestAnimationFrame(() => {
        raf = 0;
        publishAll();
      });
    };

    channel.onmessage = (ev) => {
      const data = ev.data;
      if (!isFloatSyncMessage(data)) return;
      if (data.type === "request") {
        if (data.conversationId !== conversationId) return;
        const snapshot = buildFloatProjectionSnapshot(
          data.conversationId,
          data.tabId,
        );
        postFloatSync(channel, {
          type: "snapshot",
          conversationId: data.conversationId,
          tabId: data.tabId,
          snapshot,
        });
        return;
      }
      if (data.type === "focus") {
        useSidePanelStore.getState().focusFloat(data.tabId);
      }
    };

    schedulePublish();
    const unsubSide = useSidePanelStore.subscribe(schedulePublish);
    const unsubConv = useConversationStore.subscribe(schedulePublish);
    const unsubExec = useExecutionStore.subscribe(schedulePublish);
    const unsubIx = useInteractionStore.subscribe(schedulePublish);

    return () => {
      if (raf) cancelAnimationFrame(raf);
      unsubSide();
      unsubConv();
      unsubExec();
      unsubIx();
      channel.onmessage = null;
      channel.close();
    };
    // `floats` must NOT be a dep: zIndex-only changes would tear down the
    // BroadcastChannel and republish full snapshots (flash). sidePanel
    // subscribe already covers membership / projection updates.
  }, [enabled, conversationId]);

  return null;
}

/** Close OS windows for tab ids (切对话 / clearFloats). */
export function closeOsFloatWindowsForTabs(tabIds: readonly string[]): void {
  if (!canUseOsFloatWindow()) return;
  for (const tabId of tabIds) {
    if (tabId === WORKSPACE_TAB_ID || tabId === CHANGES_TAB_ID) {
      void floatWindowDock(tabId);
    } else {
      void floatWindowDestroy(tabId);
    }
  }
}

/** Consumer: float window page hydrates stores from main-window snapshots. */
export function useFloatWindowProjectionConsumer(
  conversationId: string,
  tabId: string,
): void {
  useEffect(() => {
    if (!conversationId || !tabId) return;
    const channel = openFloatSyncChannel();
    if (!channel) return;

    const onMsg = (ev: MessageEvent<unknown>) => {
      const data = ev.data;
      if (!isFloatSyncMessage(data)) return;
      if (data.type !== "snapshot") return;
      if (data.conversationId !== conversationId || data.tabId !== tabId) {
        return;
      }
      applyFloatProjectionSnapshot(data.snapshot);
    };
    channel.onmessage = onMsg;
    postFloatSync(channel, {
      type: "request",
      conversationId,
      tabId,
    });

    const onFocus = () => {
      postFloatSync(channel, { type: "focus", tabId });
    };
    window.addEventListener("focus", onFocus);

    return () => {
      window.removeEventListener("focus", onFocus);
      channel.onmessage = null;
      channel.close();
    };
  }, [conversationId, tabId]);
}
