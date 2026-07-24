"use client";

import { useEffect, useRef } from "react";

type Node = {
  x: number;
  y: number;
  vx: number;
  vy: number;
  r: number;
  hub: boolean;
};

type Pulse = { a: number; b: number; t: number; speed: number };

/**
 * 品牌母题：一张缓慢漂移的「协作网络」。节点代表 Agent，连线代表协作，
 * 沿边游走的光点代表 Agent 间的消息/委派——把抽象的「多 Agent」变成可见的团队。
 * 颜色全部从 CSS 语义 token 读取（不硬编码），并尊重 prefers-reduced-motion。
 */
export default function CollaborationNetwork() {
  const canvasRef = useRef<HTMLCanvasElement>(null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext("2d");
    if (!ctx) return;

    // 颜色统一从品牌语义 token 读取，避免在组件内硬编码任何颜色值。
    const styles = getComputedStyle(document.documentElement);
    const colorPrimary = styles.getPropertyValue("--primary").trim();
    const colorBrand2 = styles.getPropertyValue("--brand-2").trim();
    const colorEdge = styles.getPropertyValue("--muted-foreground").trim();

    const reduceMotion = window.matchMedia(
      "(prefers-reduced-motion: reduce)",
    ).matches;

    let width = 0;
    let height = 0;
    const nodes: Node[] = [];
    const pulses: Pulse[] = [];
    const LINK_DIST = 190;

    const resize = () => {
      const parent = canvas.parentElement;
      if (!parent) return;
      width = parent.clientWidth;
      height = parent.clientHeight;
      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = Math.floor(width * dpr);
      canvas.height = Math.floor(height * dpr);
      canvas.style.width = `${width}px`;
      canvas.style.height = `${height}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    };

    const seed = () => {
      nodes.length = 0;
      const count = Math.max(
        10,
        Math.min(20, Math.round((width * height) / 52000)),
      );
      for (let i = 0; i < count; i += 1) {
        const hub = i < 2;
        nodes.push({
          x: Math.random() * width,
          y: Math.random() * height,
          vx: (Math.random() - 0.5) * 0.18,
          vy: (Math.random() - 0.5) * 0.18,
          r: hub ? 4.5 : 2 + Math.random() * 1.6,
          hub,
        });
      }
      pulses.length = 0;
    };

    const spawnPulse = () => {
      if (nodes.length < 2) return;
      const a = Math.floor(Math.random() * nodes.length);
      let b = Math.floor(Math.random() * nodes.length);
      if (b === a) b = (b + 1) % nodes.length;
      const dx = nodes[a].x - nodes[b].x;
      const dy = nodes[a].y - nodes[b].y;
      if (Math.hypot(dx, dy) > LINK_DIST) return;
      pulses.push({ a, b, t: 0, speed: 0.006 + Math.random() * 0.01 });
    };

    const draw = () => {
      ctx.clearRect(0, 0, width, height);

      // 连线
      for (let i = 0; i < nodes.length; i += 1) {
        for (let j = i + 1; j < nodes.length; j += 1) {
          const dx = nodes[i].x - nodes[j].x;
          const dy = nodes[i].y - nodes[j].y;
          const dist = Math.hypot(dx, dy);
          if (dist > LINK_DIST) continue;
          const alpha = (1 - dist / LINK_DIST) * 0.5;
          ctx.globalAlpha = alpha;
          ctx.strokeStyle = colorEdge;
          ctx.lineWidth = 1;
          ctx.beginPath();
          ctx.moveTo(nodes[i].x, nodes[i].y);
          ctx.lineTo(nodes[j].x, nodes[j].y);
          ctx.stroke();
        }
      }

      // 沿边游走的协作光点
      for (let p = pulses.length - 1; p >= 0; p -= 1) {
        const pulse = pulses[p];
        pulse.t += pulse.speed;
        if (pulse.t >= 1) {
          pulses.splice(p, 1);
          continue;
        }
        const na = nodes[pulse.a];
        const nb = nodes[pulse.b];
        const px = na.x + (nb.x - na.x) * pulse.t;
        const py = na.y + (nb.y - na.y) * pulse.t;
        ctx.globalAlpha = Math.sin(pulse.t * Math.PI) * 0.9;
        ctx.fillStyle = colorBrand2;
        ctx.beginPath();
        ctx.arc(px, py, 2.4, 0, Math.PI * 2);
        ctx.fill();
      }

      // 节点
      for (const n of nodes) {
        if (n.hub) {
          ctx.globalAlpha = 0.22;
          ctx.fillStyle = colorPrimary;
          ctx.beginPath();
          ctx.arc(n.x, n.y, n.r * 3.2, 0, Math.PI * 2);
          ctx.fill();
        }
        ctx.globalAlpha = n.hub ? 1 : 0.85;
        ctx.fillStyle = n.hub ? colorPrimary : colorBrand2;
        ctx.beginPath();
        ctx.arc(n.x, n.y, n.r, 0, Math.PI * 2);
        ctx.fill();
      }

      ctx.globalAlpha = 1;
    };

    const step = () => {
      for (const n of nodes) {
        n.x += n.vx;
        n.y += n.vy;
        if (n.x < 0 || n.x > width) n.vx *= -1;
        if (n.y < 0 || n.y > height) n.vy *= -1;
      }
      if (Math.random() < 0.04) spawnPulse();
      draw();
    };

    let raf = 0;
    const loop = () => {
      step();
      raf = requestAnimationFrame(loop);
    };

    resize();
    seed();

    if (reduceMotion) {
      draw();
    } else {
      loop();
    }

    const onResize = () => {
      resize();
      seed();
      if (reduceMotion) draw();
    };
    window.addEventListener("resize", onResize);

    return () => {
      cancelAnimationFrame(raf);
      window.removeEventListener("resize", onResize);
    };
  }, []);

  return (
    <canvas
      ref={canvasRef}
      aria-hidden="true"
      className="pointer-events-none absolute inset-0 h-full w-full"
    />
  );
}
