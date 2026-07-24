import { AgentNode } from "@/components/graph/AgentNode";
import { EndpointNode } from "@/components/graph/EndpointNode";
import { StepEdge } from "@/components/graph/StepEdge";
import { type ReactNode, useEffect, useRef, useState } from "react";

// `userInput`（非 `input`）：避开 ReactFlow 保留 type 名，否则默认样式表会给节点画
// 黑边/150px 固定宽（详见 GraphView.tsx 同处注释）。
export const nodeTypes = {
  agent: AgentNode,
  userInput: EndpointNode,
  captain: EndpointNode,
};
export const edgeTypes = { step: StepEdge };

/** `pnpm shoot:manual` 深链带 `?shoot-manual=` —— 跳过懒挂载，避免空白截图。 */
function isShootManual(): boolean {
  return (
    typeof window !== "undefined" &&
    new URLSearchParams(window.location.search).has("shoot-manual")
  );
}

/**
 * 视口懒挂载：滚动进入（提前 200px）才挂子树，避免一次性挂多个 ReactFlow。
 * 占位用 minHeight 防跳动。无头截图模式下立即挂载。
 */
export function LazyMount({
  minHeight,
  children,
}: {
  minHeight: number;
  children: ReactNode;
}) {
  const ref = useRef<HTMLDivElement | null>(null);
  const [show, setShow] = useState(isShootManual);
  useEffect(() => {
    if (show) return;
    const el = ref.current;
    if (!el) return;
    const obs = new IntersectionObserver(
      (entries) => {
        if (entries.some((e) => e.isIntersecting)) {
          setShow(true);
          obs.disconnect();
        }
      },
      { rootMargin: "200px 0px" },
    );
    obs.observe(el);
    return () => obs.disconnect();
  }, [show]);
  return (
    <div ref={ref} style={show ? undefined : { minHeight }}>
      {show ? children : null}
    </div>
  );
}

/** 系统「减少动态效果」开关：尊重它就停在终帧静态展示，不自动播放。 */
export function usePrefersReducedMotion(): boolean {
  const [reduced, setReduced] = useState(false);
  useEffect(() => {
    const mq = window.matchMedia("(prefers-reduced-motion: reduce)");
    setReduced(mq.matches);
    const on = (e: MediaQueryListEvent) => setReduced(e.matches);
    mq.addEventListener("change", on);
    return () => mq.removeEventListener("change", on);
  }, []);
  return reduced;
}
