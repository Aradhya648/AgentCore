import * as THREE from "three";

/**
 * 品牌 OKLCH 语义 token → three.js 颜色。
 * three 不认识 oklch()，故经由 2D canvas 让浏览器解析成 sRGB 字节再喂给 THREE.Color，
 * 保证 3D 场景颜色与站点 token 单一来源（globals.css :root）。仅客户端调用。
 */

let probeCtx: CanvasRenderingContext2D | null = null;

export function cssVarColor(varName: string): THREE.Color {
  if (!probeCtx) {
    const canvas = document.createElement("canvas");
    canvas.width = 1;
    canvas.height = 1;
    probeCtx = canvas.getContext("2d", { willReadFrequently: true });
  }
  const ctx = probeCtx;
  if (!ctx) return new THREE.Color(0.5, 0.5, 0.5);

  const raw = getComputedStyle(document.documentElement)
    .getPropertyValue(varName)
    .trim();
  ctx.clearRect(0, 0, 1, 1);
  // 先设兜底再设目标值：非法/缺失 token 时保留兜底灰，不抛错。
  ctx.fillStyle = "#808080";
  if (raw) ctx.fillStyle = raw;
  ctx.fillRect(0, 0, 1, 1);
  const d = ctx.getImageData(0, 0, 1, 1).data;
  return new THREE.Color().setRGB(
    d[0] / 255,
    d[1] / 255,
    d[2] / 255,
    THREE.SRGBColorSpace,
  );
}

export type UniversePalette = {
  background: THREE.Color;
  foreground: THREE.Color;
  muted: THREE.Color;
  primary: THREE.Color;
  brand2: THREE.Color;
  warning: THREE.Color;
  success: THREE.Color;
  glow1: THREE.Color;
  glow2: THREE.Color;
  /** --agent-1 … --agent-8 身份色 */
  agents: THREE.Color[];
};

export function buildPalette(): UniversePalette {
  return {
    background: cssVarColor("--background"),
    foreground: cssVarColor("--foreground"),
    muted: cssVarColor("--muted-foreground"),
    primary: cssVarColor("--primary"),
    brand2: cssVarColor("--brand-2"),
    warning: cssVarColor("--warning"),
    success: cssVarColor("--success"),
    glow1: cssVarColor("--glow-1"),
    glow2: cssVarColor("--glow-2"),
    agents: Array.from({ length: 8 }, (_, i) =>
      cssVarColor(`--agent-${i + 1}`),
    ),
  };
}
