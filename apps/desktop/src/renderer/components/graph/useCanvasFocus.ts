/** 聚焦回合、相机 framing、上滚分页、节点交互。 */

import { loadOlderMessages } from "@/services/messages";
import {
  useActiveError,
  useActiveHasMoreBefore,
  useActiveLoadingOlder,
  useConversationStore,
} from "@/stores/conversation";
import { turnDetailPath } from "@/stores/ui";
import type { Node, ReactFlowInstance } from "@xyflow/react";
import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useRef,
  useState,
} from "react";
import { useNavigate } from "react-router-dom";
import { GAP_Y, type TurnItem, spineTurnHeight } from "./useCanvasTurns";

export const TOP_LOAD_THRESHOLD_PX = 240;

interface UseCanvasFocusOptions {
  turns: TurnItem[];
  effectiveFocus: string | null;
  nodes: Node[];
}

export function useCanvasFocusState() {
  const [focusedTurn, setFocusedTurn] = useState<string | null>(null);
  const setFocusedTurnStable = useCallback((id: string) => {
    setFocusedTurn(id);
  }, []);
  return { focusedTurn, setFocusedTurn: setFocusedTurnStable };
}

export function useCanvasFocus({
  turns,
  effectiveFocus,
  nodes,
}: UseCanvasFocusOptions) {
  const hasMoreBefore = useActiveHasMoreBefore();
  const loadingOlder = useActiveLoadingOlder();
  const conversationId = useConversationStore((s) => s.currentConversationId);

  const rfRef = useRef<ReactFlowInstance | null>(null);
  const canvasBoxRef = useRef<HTMLDivElement>(null);

  const pagingAnchorRef = useRef<{
    oldestId: string;
    vpX: number;
    vpY: number;
    zoom: number;
  } | null>(null);
  const pagingStateRef = useRef({
    hasMoreBefore,
    loadingOlder,
    conversationId,
    turns,
  });
  pagingStateRef.current = {
    hasMoreBefore,
    loadingOlder,
    conversationId,
    turns,
  };

  const requestOlder = useCallback(() => {
    const rf = rfRef.current;
    const s = pagingStateRef.current;
    if (!rf || !s.hasMoreBefore || s.loadingOlder || pagingAnchorRef.current)
      return;
    const oldestId = s.turns[0]?.id;
    if (!s.conversationId || !oldestId) return;
    const vp = rf.getViewport();
    pagingAnchorRef.current = { oldestId, vpX: vp.x, vpY: vp.y, zoom: vp.zoom };
    void loadOlderMessages(s.conversationId);
  }, []);

  const onMove = useCallback(
    (_: unknown, viewport: { x: number; y: number; zoom: number }) => {
      if (viewport.y <= -TOP_LOAD_THRESHOLD_PX) return;
      requestOlder();
    },
    [requestOlder],
  );

  useLayoutEffect(() => {
    const a = pagingAnchorRef.current;
    if (!a) return;
    const newOldest = turns[0]?.id;
    const rf = rfRef.current;
    if (rf && newOldest && newOldest !== a.oldestId) {
      let deltaY = 0;
      for (const t of turns) {
        if (t.id === a.oldestId) break;
        // #3: use real spine height (summary vs expanded turnGroup)
        deltaY += spineTurnHeight(t, nodes) + GAP_Y;
      }
      rf.setViewport({ x: a.vpX, y: a.vpY - deltaY * a.zoom, zoom: a.zoom });
      pagingAnchorRef.current = null;
    } else if (!loadingOlder) {
      pagingAnchorRef.current = null;
    }
  }, [turns, loadingOlder, nodes]);

  // Fit to focused turn (overview).
  const fitTarget = effectiveFocus;
  const prevFitKeyRef = useRef<string | null>(null);
  useEffect(() => {
    const rf = rfRef.current;
    if (!rf || !fitTarget) return;
    if (pagingAnchorRef.current) return;
    const fitKey = `${fitTarget}:overview`;
    if (prevFitKeyRef.current === fitKey) return;
    if (!nodes.some((x) => x.id === fitTarget)) return;
    prevFitKeyRef.current = fitKey;
    rf.fitView({
      nodes: [{ id: fitTarget }],
      padding: 0.2,
      maxZoom: 1,
      duration: 400,
    });
  }, [fitTarget, nodes]);

  const fitTargetRef = useRef<string | null>(fitTarget);
  fitTargetRef.current = fitTarget;
  useEffect(() => {
    const el = canvasBoxRef.current;
    if (!el) return;
    let lastWidth = Math.round(el.clientWidth);
    let settled = false;
    let timer: ReturnType<typeof setTimeout> | undefined;
    const ro = new ResizeObserver((entries) => {
      const w = Math.round(entries[0]?.contentRect.width ?? 0);
      if (!settled) {
        settled = true;
        lastWidth = w;
        return;
      }
      if (w <= 0 || w === lastWidth) return;
      lastWidth = w;
      clearTimeout(timer);
      timer = setTimeout(() => {
        const rf = rfRef.current;
        const focus = fitTargetRef.current;
        if (!rf || !focus || !rf.getNode(focus)) return;
        if (pagingAnchorRef.current) return;
        rf.fitView({
          nodes: [{ id: focus }],
          padding: 0.2,
          maxZoom: 1,
          duration: 300,
        });
      }, 160);
    });
    ro.observe(el);
    return () => {
      clearTimeout(timer);
      ro.disconnect();
    };
  }, []);

  const convError = useActiveError();

  const onInit = useCallback((inst: ReactFlowInstance) => {
    rfRef.current = inst;
    inst.fitView({ padding: 0.2, maxZoom: 1 });
  }, []);

  return {
    rfRef,
    canvasBoxRef,
    hasMoreBefore,
    loadingOlder,
    convError,
    requestOlder,
    onMove,
    onInit,
  };
}

/**
 * Click / double-click / Maximize semantics on the conversation canvas:
 * - click `teamTurn` → focus + expand that turn (LRU window, max 3)
 * - click `simpleTurn` → open side-panel Q&A tab (full prompt + answer)
 * - double-click `teamTurn` → navigate to full-screen turn detail
 * - `turnGroup` body is non-interactive; Maximize button is the only detail entry
 *   from the expanded compound (avoids accidental double-click on DAG children)
 * - DAG agent nodes: single click activates (handled by ConversationCanvas)
 */
export function useCanvasNodeHandlers(
  setFocusedTurn: (id: string) => void,
  onExpandTurn?: (turnId: string) => void,
  onSimpleTurnClick?: (turnId: string) => void,
) {
  const navigate = useNavigate();
  const conversationId = useConversationStore((s) => s.currentConversationId);

  const onNodeClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      if (node.type === "teamTurn") {
        onExpandTurn?.(node.id);
        setFocusedTurn(node.id);
      } else if (node.type === "simpleTurn") {
        onSimpleTurnClick?.(node.id);
      }
      // turnGroup: ignore — header Maximize is the explicit detail control
    },
    [setFocusedTurn, onExpandTurn, onSimpleTurnClick],
  );

  const onNodeDoubleClick = useCallback(
    (_: React.MouseEvent, node: Node) => {
      // Only folded team summaries open turn detail on double-click.
      // Expanded turnGroup / DAG children must not — Maximize button owns that.
      if (node.type === "teamTurn" && conversationId) {
        navigate(turnDetailPath(conversationId, node.id));
      }
    },
    [navigate, conversationId],
  );

  const makeOnRailSelect = useCallback(
    (rfRef: React.RefObject<ReactFlowInstance | null>) =>
      (id: string, kind: "team" | "simple") => {
        if (kind === "team") {
          onExpandTurn?.(id);
          setFocusedTurn(id);
        } else {
          rfRef.current?.fitView({
            nodes: [{ id }],
            padding: 0.3,
            maxZoom: 1,
            duration: 300,
          });
        }
      },
    [setFocusedTurn, onExpandTurn],
  );

  return { onNodeClick, onNodeDoubleClick, makeOnRailSelect };
}
