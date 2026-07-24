/** Fit-to-width viewport, resize observers, and zoom helpers for GraphView.
 * Host contract (Provider / fit / overflow) → `graphHost.tsx`. */

import { fitWidthBox } from "@/lib/elk-layout";
import type { ReactFlowInstance } from "@xyflow/react";
import { useCallback, useEffect, useRef, useState } from "react";
import { prefersReducedMotion } from "./constants";
import type { GraphFitMode } from "./graphHost";

export type { GraphFitMode };

interface UseGraphViewportOptions {
  fitMode: GraphFitMode;
  /** Content bbox from computeLayout (origin pinned near padding; no dead band). */
  bbox: { width: number; height: number } | null;
  layoutReady: boolean;
  onMeasure?: (m: { height: number; overflowing: boolean }) => void;
}

export function useGraphViewport({
  fitMode,
  bbox,
  layoutReady,
  onMeasure,
}: UseGraphViewportOptions) {
  const rfRef = useRef<ReactFlowInstance | null>(null);
  const containerRef = useRef<HTMLDivElement | null>(null);
  const [colWidth, setColWidth] = useState(0);
  const [colHeight, setColHeight] = useState(0);
  const [rfInstance, setRfInstance] = useState<ReactFlowInstance | null>(null);
  const [overflowing, setOverflowing] = useState(false);
  const viewportSettledRef = useRef(false);

  useEffect(() => {
    if (!layoutReady) {
      viewportSettledRef.current = false;
    }
  }, [layoutReady]);

  const onInit = useCallback((inst: ReactFlowInstance) => {
    rfRef.current = inst;
    setRfInstance(inst);
  }, []);

  const fitView = useCallback(() => {
    rfRef.current?.fitView({ padding: 0.2, duration: 300 });
  }, []);

  const centerNode = useCallback((id: string) => {
    const node = rfRef.current?.getNode(id);
    if (!node) return;
    const w = node.measured?.width ?? 210;
    const h = node.measured?.height ?? 64;
    rfRef.current?.setCenter(node.position.x + w / 2, node.position.y + h / 2, {
      zoom: 1.2,
      duration: 300,
    });
  }, []);

  useEffect(() => {
    if (fitMode !== "width" && fitMode !== "contain") return;
    const el = containerRef.current;
    if (!el) return;
    setColWidth(el.clientWidth);
    if (fitMode === "contain") setColHeight(el.clientHeight);
    const ro = new ResizeObserver((entries) => {
      const rect = entries[0]?.contentRect;
      const w = rect?.width ?? 0;
      if (w > 0) setColWidth(w);
      if (fitMode === "contain") {
        const h = rect?.height ?? 0;
        if (h > 0) setColHeight(h);
      }
    });
    ro.observe(el);
    return () => ro.disconnect();
  }, [fitMode]);

  useEffect(() => {
    if (
      fitMode !== "width" ||
      !rfInstance ||
      !bbox ||
      colWidth <= 0 ||
      !layoutReady
    ) {
      return;
    }
    // bbox is the placed-content footprint (computeLayout normalizes origin).
    // Never assume a phantom band above y=0 — pin overflow to the content top.
    const fit = fitWidthBox(bbox.width, bbox.height, colWidth);
    const x = Math.max(0, (colWidth - fit.renderedWidth) / 2);
    const y =
      fit.renderedHeight <= fit.height
        ? (fit.height - fit.renderedHeight) / 2
        : 0;
    const animate = viewportSettledRef.current && !prefersReducedMotion();
    rfInstance.setViewport(
      { x, y, zoom: fit.zoom },
      animate ? { duration: 200 } : undefined,
    );
    viewportSettledRef.current = true;
    setOverflowing(fit.overflowing);
    onMeasure?.({ height: fit.height, overflowing: fit.overflowing });
  }, [fitMode, rfInstance, bbox, colWidth, layoutReady, onMeasure]);

  useEffect(() => {
    if (
      fitMode !== "contain" ||
      !rfInstance ||
      !bbox ||
      colWidth <= 0 ||
      colHeight <= 0 ||
      !layoutReady
    ) {
      return;
    }
    const zoom = Math.min(1, colWidth / bbox.width, colHeight / bbox.height);
    const renderedW = bbox.width * zoom;
    const renderedH = bbox.height * zoom;
    const x = Math.max(0, (colWidth - renderedW) / 2);
    const y = Math.max(0, (colHeight - renderedH) / 2);
    const animate = viewportSettledRef.current && !prefersReducedMotion();
    rfInstance.setViewport(
      { x, y, zoom },
      animate ? { duration: 200 } : undefined,
    );
    viewportSettledRef.current = true;
  }, [fitMode, rfInstance, bbox, colWidth, colHeight, layoutReady]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "f" && e.key !== "F") return;
      if (e.metaKey || e.ctrlKey || e.altKey) return;
      const t = e.target as HTMLElement | null;
      if (
        t &&
        (t.tagName === "INPUT" ||
          t.tagName === "TEXTAREA" ||
          t.isContentEditable)
      ) {
        return;
      }
      e.preventDefault();
      fitView();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [fitView]);

  useEffect(() => {
    if (fitMode !== "view") return;
    const el = containerRef.current;
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
      timer = setTimeout(() => fitView(), 160);
    });
    ro.observe(el);
    return () => {
      clearTimeout(timer);
      ro.disconnect();
    };
  }, [fitMode, fitView]);

  return {
    containerRef,
    rfRef,
    overflowing,
    fitView,
    centerNode,
    onInit,
  };
}
