/**
 * Layout morph — the single implementation of the brief CSS transition the graph
 * plays when node positions change (structure churn), shared by every host.
 * Streaming content updates don't move positions, so the signature is unchanged
 * and no morph fires. Hosts compute their own layout signature (single turn vs
 * per-turn spine) and feed it here; the state + 320ms timer live only here.
 */

import { useEffect, useRef, useState } from "react";

const MORPH_MS = 320;

/** Position-only morph signature for a single laid-out turn (GraphView). */
export function positionsMorphSig(
  positions: Record<string, { x: number; y: number }>,
): string {
  return Object.keys(positions)
    .sort()
    .map((id) => {
      const p = positions[id];
      return `${id}:${p?.x ?? 0},${p?.y ?? 0}`;
    })
    .join("|");
}

/** Full structural signature (positions + node sizes). */
export function layoutStructureSig(
  positions: Record<string, { x: number; y: number }>,
  nodeSizes: Record<string, { width: number; height: number }>,
): string {
  const pos = Object.entries(positions)
    .map(([k, v]) => `${k}:${v.x},${v.y}`)
    .join("|");
  const sizes = Object.entries(nodeSizes)
    .map(([k, v]) => `${k}:${v.width}x${v.height}`)
    .join("|");
  return `${pos}#${sizes}`;
}

/** True for ~320ms after `layoutSig` changes (skips the first settled layout). */
export function useLayoutMorph(layoutSig: string): boolean {
  const [morphing, setMorphing] = useState(false);
  const morphTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const prevLayoutSigRef = useRef("");

  useEffect(() => {
    if (!layoutSig || layoutSig === prevLayoutSigRef.current) return;
    const hadPrev = prevLayoutSigRef.current.length > 0;
    prevLayoutSigRef.current = layoutSig;
    if (!hadPrev) return;
    setMorphing(true);
    if (morphTimerRef.current) clearTimeout(morphTimerRef.current);
    morphTimerRef.current = setTimeout(() => setMorphing(false), MORPH_MS);
    return () => {
      if (morphTimerRef.current) clearTimeout(morphTimerRef.current);
    };
  }, [layoutSig]);

  return morphing;
}
