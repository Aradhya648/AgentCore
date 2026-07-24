"use client";

import { type ComponentRef, useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import { Line } from "@react-three/drei";
import * as THREE from "three";
import type { UniversePalette } from "./palette";
import { SEC, clamp01, progressStore, windowProgress } from "./timeline";

/**
 * 「协作星座」——把一次多 Agent 协作演成一片星空：
 * 你 → CEO 点亮 → 委派光束长出三波团队 → 波间产物流动、席间辩论交锋 →
 * 评审汇聚 → 交付。节点=Agent（发光星体），实线=任务流，虚线=协作通信，
 * 大弧线=阻塞升级回到「你」。全部出场时刻由全局滚动进度驱动（timeline.ts）。
 */

/* ── 图数据 ── */

type NodeKind = "you" | "ceo" | "worker" | "debate" | "reviewer" | "final";

type NodeDef = {
  id: string;
  label: string;
  pos: [number, number, number];
  /** palette.agents 下标；-1 = 特殊色（you/ceo/final 由 kind 决定） */
  agent: number;
  radius: number;
  appearAt: number;
  kind: NodeKind;
  moons: number;
};

export const NODES: NodeDef[] = [
  { id: "you", label: "你 · 领导者", pos: [0, -0.6, 14.5], agent: -1, radius: 0.52, appearAt: 0.255, kind: "you", moons: 0 },
  { id: "ceo", label: "CEO 主 Agent", pos: [0, 0, 8], agent: -1, radius: 0.72, appearAt: 0, kind: "ceo", moons: 0 },
  { id: "w1a", label: "市场调研", pos: [-4.5, 1.8, 0.5], agent: 0, radius: 0.5, appearAt: 0.312, kind: "worker", moons: 2 },
  { id: "w1b", label: "竞品检索", pos: [0.8, -2.6, 0], agent: 1, radius: 0.5, appearAt: 0.334, kind: "worker", moons: 3 },
  { id: "w1c", label: "用户访谈", pos: [4.9, 2.7, -1.3], agent: 2, radius: 0.5, appearAt: 0.356, kind: "worker", moons: 1 },
  { id: "w2a", label: "数据分析", pos: [-2.6, 0.8, -7], agent: 3, radius: 0.5, appearAt: 0.455, kind: "worker", moons: 2 },
  { id: "w2b", label: "用户画像", pos: [3, -1.2, -7.5], agent: 4, radius: 0.5, appearAt: 0.482, kind: "worker", moons: 1 },
  { id: "dpro", label: "方案 · 正方", pos: [-2.4, 1.6, -14], agent: 6, radius: 0.52, appearAt: 0.595, kind: "debate", moons: 0 },
  { id: "dcon", label: "方案 · 反方", pos: [2.6, 1.1, -14.2], agent: 7, radius: 0.52, appearAt: 0.612, kind: "debate", moons: 0 },
  { id: "rev", label: "评审", pos: [0.2, 3.6, -15.8], agent: 5, radius: 0.5, appearAt: 0.638, kind: "reviewer", moons: 0 },
  { id: "final", label: "综合交付", pos: [0, -0.2, -20.5], agent: -1, radius: 0.62, appearAt: 0.732, kind: "final", moons: 0 },
];

const NODE_BY_ID = new Map(NODES.map((n) => [n.id, n]));

type EdgeKind = "flow" | "comm" | "debate" | "escalate";

type EdgeDef = {
  from: string;
  to: string;
  kind: EdgeKind;
  /** 画线（draw-on）进度窗口 */
  start: number;
  end: number;
  /** 弧线鼓出量（世界单位）；默认按边长自适应 */
  bulge?: number;
  /** 抬升量（+y），escalate 大弧用 */
  lift?: number;
};

export const EDGES: EdgeDef[] = [
  { from: "you", to: "ceo", kind: "flow", start: 0.265, end: 0.295 },
  { from: "ceo", to: "w1a", kind: "flow", start: 0.295, end: 0.33 },
  { from: "ceo", to: "w1b", kind: "flow", start: 0.316, end: 0.352 },
  { from: "ceo", to: "w1c", kind: "flow", start: 0.338, end: 0.374 },
  { from: "w1a", to: "w1b", kind: "comm", start: 0.415, end: 0.45 },
  { from: "w1a", to: "w2a", kind: "flow", start: 0.432, end: 0.472 },
  { from: "w1b", to: "w2a", kind: "flow", start: 0.448, end: 0.488 },
  { from: "w1b", to: "w2b", kind: "flow", start: 0.462, end: 0.502 },
  { from: "w1c", to: "w2b", kind: "flow", start: 0.476, end: 0.516 },
  { from: "w2a", to: "w2b", kind: "comm", start: 0.505, end: 0.535 },
  { from: "w2a", to: "dpro", kind: "flow", start: 0.578, end: 0.614 },
  { from: "w2b", to: "dcon", kind: "flow", start: 0.594, end: 0.63 },
  { from: "dpro", to: "dcon", kind: "debate", start: 0.622, end: 0.648 },
  { from: "dpro", to: "rev", kind: "flow", start: 0.652, end: 0.682 },
  { from: "dcon", to: "rev", kind: "flow", start: 0.662, end: 0.692 },
  { from: "rev", to: "final", kind: "flow", start: 0.712, end: 0.752 },
  { from: "w1c", to: "you", kind: "escalate", start: 0.762, end: 0.812, lift: 5.5, bulge: 2.5 },
];

/* ── 纹理（模块级懒建，仅客户端） ── */

let radialTex: THREE.Texture | null = null;

function getRadialTexture(): THREE.Texture {
  if (radialTex) return radialTex;
  const size = 128;
  const canvas = document.createElement("canvas");
  canvas.width = size;
  canvas.height = size;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    const g = ctx.createRadialGradient(
      size / 2, size / 2, 0,
      size / 2, size / 2, size / 2,
    );
    g.addColorStop(0, "rgba(255,255,255,1)");
    g.addColorStop(0.22, "rgba(255,255,255,0.55)");
    g.addColorStop(0.55, "rgba(255,255,255,0.14)");
    g.addColorStop(1, "rgba(255,255,255,0)");
    ctx.fillStyle = g;
    ctx.fillRect(0, 0, size, size);
  }
  radialTex = new THREE.CanvasTexture(canvas);
  radialTex.colorSpace = THREE.SRGBColorSpace;
  return radialTex;
}

const LABEL_FONT =
  '-apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Noto Sans SC", "PingFang SC", "Microsoft YaHei", sans-serif';

function makeLabelTexture(
  text: string,
  colorCss: string,
): { tex: THREE.Texture; aspect: number } {
  const dpr = 2;
  const fontPx = 34 * dpr;
  const padX = 18 * dpr;
  const h = 56 * dpr;
  const measurer = document.createElement("canvas").getContext("2d");
  let w = 200 * dpr;
  if (measurer) {
    measurer.font = `600 ${fontPx}px ${LABEL_FONT}`;
    w = Math.ceil(measurer.measureText(text).width) + padX * 2;
  }
  const canvas = document.createElement("canvas");
  canvas.width = w;
  canvas.height = h;
  const ctx = canvas.getContext("2d");
  if (ctx) {
    ctx.font = `600 ${fontPx}px ${LABEL_FONT}`;
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillStyle = colorCss;
    ctx.fillText(text, w / 2, h / 2 + dpr);
  }
  const tex = new THREE.CanvasTexture(canvas);
  tex.colorSpace = THREE.SRGBColorSpace;
  tex.anisotropy = 4;
  return { tex, aspect: w / h };
}

/* ── 共享几何 ── */

const sphereGeo = new THREE.SphereGeometry(1, 24, 24);
const torusGeo = new THREE.TorusGeometry(1.55, 0.018, 8, 72);

/* ── 小工具 ── */

function easeOutBack(t: number): number {
  const c1 = 1.70158;
  const c3 = c1 + 1;
  const x = clamp01(t) - 1;
  return 1 + c3 * x * x * x + c1 * x * x;
}

/** 三角波 0→1→0（comm 脉冲往返用） */
function pingpong(t: number): number {
  return 1 - Math.abs(1 - 2 * (t % 1));
}

function nodeColor(def: NodeDef, pal: UniversePalette): THREE.Color {
  if (def.kind === "you") return pal.brand2;
  if (def.kind === "ceo") return pal.primary;
  if (def.kind === "final") return pal.success;
  return pal.agents[def.agent] ?? pal.primary;
}

function edgeColor(kind: EdgeKind, to: string, pal: UniversePalette): THREE.Color {
  if (kind === "comm") return pal.brand2;
  if (kind === "debate" || kind === "escalate") return pal.warning;
  if (to === "final") return pal.success;
  return pal.primary;
}

function buildCurve(def: EdgeDef): THREE.QuadraticBezierCurve3 {
  const a = new THREE.Vector3(...(NODE_BY_ID.get(def.from)?.pos ?? [0, 0, 0]));
  const b = new THREE.Vector3(...(NODE_BY_ID.get(def.to)?.pos ?? [0, 0, 0]));
  const mid = a.clone().add(b).multiplyScalar(0.5);
  const dir = b.clone().sub(a).normalize();
  const side = new THREE.Vector3().crossVectors(dir, new THREE.Vector3(0, 1, 0));
  if (side.lengthSq() < 1e-4) side.set(1, 0, 0);
  side.normalize();
  const dist = a.distanceTo(b);
  const bulge = def.bulge ?? dist * 0.1;
  mid.addScaledVector(side, bulge);
  mid.y += def.lift ?? dist * 0.06;
  return new THREE.QuadraticBezierCurve3(a, mid, b);
}

/* ── 边（Line2 宽线：draw-on 生长 + 流动虚线 + 随进度点亮） ── */

function Edge({ def, pal }: { def: EdgeDef; pal: UniversePalette }) {
  const segments = def.kind === "escalate" ? 56 : 30;
  const ref = useRef<ComponentRef<typeof Line>>(null);

  const { points, color } = useMemo(() => {
    const curve = buildCurve(def);
    return {
      points: curve.getPoints(segments),
      color: edgeColor(def.kind, def.to, pal),
    };
  }, [def, pal, segments]);

  const dashed = def.kind !== "flow";
  const baseOpacity =
    def.kind === "flow" ? 0.66 : def.kind === "comm" ? 0.52 : 0.9;
  const width =
    def.kind === "flow" ? 2.1 : def.kind === "comm" ? 1.5 : 2.3;

  useFrame((_, dt) => {
    const line = ref.current;
    if (!line) return;
    const p = progressStore.value;
    const t = windowProgress(p, def.start, def.end);
    line.geometry.instanceCount =
      t <= 0 ? 0 : Math.max(1, Math.round(t * segments));
    const mat = line.material;
    mat.opacity = baseOpacity * (0.35 + 0.65 * t);
    // 虚线流动：通信/辩论/升级边持续「传输中」
    if (dashed && !progressStore.reducedMotion) {
      mat.dashOffset -= dt * (def.kind === "debate" ? 2.2 : 1.1);
    }
  });

  return (
    <Line
      ref={ref}
      points={points}
      color={color}
      lineWidth={width}
      transparent
      opacity={0}
      dashed={dashed}
      dashSize={def.kind === "escalate" ? 0.5 : 0.3}
      gapSize={def.kind === "escalate" ? 0.38 : 0.24}
      blending={THREE.AdditiveBlending}
      depthWrite={false}
      frustumCulled={false}
    />
  );
}

/* ── 沿边游走的脉冲（产物/消息） ── */

function Pulse({
  def,
  pal,
  phase,
}: {
  def: EdgeDef;
  pal: UniversePalette;
  phase: number;
}) {
  const ref = useRef<THREE.Sprite>(null);
  const curve = useMemo(() => buildCurve(def), [def]);
  const color = useMemo(() => edgeColor(def.kind, def.to, pal), [def, pal]);
  const period =
    def.kind === "debate" ? 1.6 : def.kind === "escalate" ? 5 : 3.4;
  const size =
    def.kind === "debate" ? 0.3 : def.kind === "comm" ? 0.24 : 0.36;

  useFrame(({ clock }) => {
    const sprite = ref.current;
    if (!sprite) return;
    const p = progressStore.value;
    const drawn = windowProgress(p, def.end - 0.008, def.end);
    const active = drawn > 0.98 && !progressStore.reducedMotion;
    sprite.visible = active;
    if (!active) return;
    // 「全程可见」章节后整图提速，画面更有生命力。
    const speedUp = 1 + windowProgress(p, SEC(5), SEC(5) + 0.06) * 0.65;
    const cyc = (clock.elapsedTime * speedUp) / period + phase;
    const t =
      def.kind === "comm" || def.kind === "debate"
        ? pingpong(cyc)
        : cyc % 1;
    sprite.position.copy(curve.getPoint(t));
    const throb = 1 + 0.22 * Math.sin(clock.elapsedTime * 5.5 + phase * 17);
    sprite.scale.setScalar(size * throb);
  });

  return (
    <sprite ref={ref} visible={false}>
      <spriteMaterial
        map={getRadialTexture()}
        color={color}
        transparent
        opacity={0.95}
        blending={THREE.AdditiveBlending}
        depthWrite={false}
        toneMapped={false}
      />
    </sprite>
  );
}

/* ── 节点（星体 + 光晕 + 标签 + 卫星工具） ── */

function Moons({ def, pal }: { def: NodeDef; pal: UniversePalette }) {
  const group = useRef<THREE.Group>(null);
  const moons = useMemo(
    () =>
      Array.from({ length: def.moons }, (_, i) => ({
        orbit: def.radius + 0.42 + i * 0.2,
        speed: (0.5 + (i % 3) * 0.24) * (i % 2 === 0 ? 1 : -1),
        phase: (i / def.moons) * Math.PI * 2 + def.pos[0],
        incline: 0.35 + (i % 2) * 0.5,
      })),
    [def],
  );
  const color = useMemo(() => nodeColor(def, pal).clone().lerp(pal.foreground, 0.55), [def, pal]);

  useFrame(({ clock }) => {
    const g = group.current;
    if (!g) return;
    const t = progressStore.reducedMotion ? 0 : clock.elapsedTime;
    g.children.forEach((child, i) => {
      const m = moons[i];
      const a = m.phase + t * m.speed;
      child.position.set(
        Math.cos(a) * m.orbit,
        Math.sin(a) * m.orbit * Math.sin(m.incline) * 0.5,
        Math.sin(a) * m.orbit * Math.cos(m.incline),
      );
    });
  });

  if (def.moons === 0) return null;
  return (
    <group ref={group}>
      {moons.map((m) => (
        <mesh key={m.phase} geometry={sphereGeo} scale={0.07}>
          <meshBasicMaterial color={color} toneMapped={false} />
        </mesh>
      ))}
    </group>
  );
}

function NodeStar({ def, pal }: { def: NodeDef; pal: UniversePalette }) {
  const group = useRef<THREE.Group>(null);
  const core = useRef<THREE.Mesh>(null);
  const hotspot = useRef<THREE.Sprite>(null);
  const halo = useRef<THREE.Sprite>(null);
  const label = useRef<THREE.Sprite>(null);
  const altLabel = useRef<THREE.Sprite>(null);
  const ring = useRef<THREE.Mesh>(null);

  const base = useMemo(() => nodeColor(def, pal), [def, pal]);
  const labelData = useMemo(
    () => makeLabelTexture(def.label, `#${pal.foreground.getHexString()}`),
    [def, pal],
  );
  // CEO 点亮前的「孤独智能」备用标签
  const altLabelData = useMemo(
    () =>
      def.kind === "ceo"
        ? makeLabelTexture("一个孤独的智能", `#${pal.muted.getHexString()}`)
        : null,
    [def, pal],
  );

  const coreMat = useMemo(
    () =>
      new THREE.MeshBasicMaterial({
        color: base.clone(),
        toneMapped: false,
        transparent: true,
        opacity: 1,
      }),
    [base],
  );

  const labelAspect = labelData.aspect;
  const altAspect = altLabelData?.aspect ?? 1;
  const hotColor = useMemo(
    () => base.clone().lerp(pal.foreground, 0.72),
    [base, pal],
  );

  useFrame(({ clock, camera }) => {
    const g = group.current;
    if (!g) return;
    const p = progressStore.value;
    const time = clock.elapsedTime;
    // 标签屏幕等大：按相机距离反算世界尺寸（近景不糊脸、远景不消失）
    const dist = camera.position.distanceTo(g.position);
    const labelScale = Math.min(1.05, Math.max(0.36, dist * 0.034));

    // 出场：弹性放大
    const born =
      def.appearAt <= 0
        ? 1
        : easeOutBack(windowProgress(p, def.appearAt, def.appearAt + 0.028));
    // CEO 点亮：颜色从 muted 淡蓝渐变到品牌蓝，亮度骤增
    const ignite =
      def.kind === "ceo" ? windowProgress(p, 0.272, 0.308) : 1;

    // 出场瞬间的高亮脉冲：升起后随即衰减，避免常亮过曝成白球
    const flash =
      windowProgress(p, def.appearAt, def.appearAt + 0.02) *
      (1 - windowProgress(p, def.appearAt + 0.05, def.appearAt + 0.12));
    let brightness = 0.8 + flash * 0.85;
    if (def.kind === "ceo") brightness = 0.72 + ignite * (0.56 + flash * 0.4);
    if (def.kind === "final")
      brightness = 0.8 + windowProgress(p, 0.74, 0.78) * 0.45;

    const breath = progressStore.reducedMotion
      ? 0
      : Math.sin(time * 1.4 + def.pos[0] * 2.3) * 0.035;
    const scale = Math.max(0.0001, born * (1 + breath));
    g.scale.setScalar(scale);
    g.visible = born > 0.001;

    if (def.kind === "ceo") {
      // 点亮前是一颗冷暗的孤星：核心半透明缩小、让光晕主导，避免「灰饼」观感
      coreMat.color
        .copy(pal.muted)
        .lerp(base, ignite)
        .multiplyScalar(brightness);
      coreMat.opacity = 0.52 + 0.48 * ignite;
      if (core.current) {
        core.current.scale.setScalar(def.radius * (0.5 + 0.5 * ignite));
      }
    } else {
      coreMat.color.copy(base).multiplyScalar(brightness);
    }

    if (halo.current) {
      const m = halo.current.material as THREE.SpriteMaterial;
      m.opacity = 0.32 + 0.3 * clamp01(brightness - 0.6);
      if (def.kind === "ceo") m.color.copy(pal.muted).lerp(base, ignite);
      const haloBreath = progressStore.reducedMotion
        ? 0
        : Math.sin(time * 1.1 + def.pos[2]) * 0.08;
      halo.current.scale.setScalar(def.radius * (5 + haloBreath));
    }

    if (hotspot.current) {
      const m = hotspot.current.material as THREE.SpriteMaterial;
      // 内核高光：让球体呈「从内发光」而非平面色饼；孤星阶段熄灭
      m.opacity = (def.kind === "ceo" ? ignite : 1) * (0.5 + flash * 0.35);
      hotspot.current.scale.setScalar(def.radius * 1.7);
    }

    if (label.current) {
      const m = label.current.material as THREE.SpriteMaterial;
      const labelIn =
        def.kind === "ceo"
          ? ignite
          : windowProgress(p, def.appearAt + 0.012, def.appearAt + 0.04);
      // 终章淡出标签：星座退为干净的背景天际线，别与 CTA 面板文字打架
      const finaleFade = 1 - windowProgress(p, 0.86, 0.94);
      m.opacity = labelIn * 0.92 * finaleFade;
      label.current.scale.set(labelAspect * labelScale, labelScale, 1);
      label.current.position.y = -(def.radius + 0.3 + labelScale * 0.62);
    }
    if (altLabel.current) {
      const m = altLabel.current.material as THREE.SpriteMaterial;
      // 「孤独章节」出现，点亮后让位给正式头衔
      m.opacity =
        windowProgress(p, SEC(1) - 0.07, SEC(1) - 0.02) * (1 - ignite) * 0.85;
      const s = labelScale * 0.86;
      altLabel.current.scale.set(altAspect * s, s, 1);
      altLabel.current.position.y = -(def.radius + 0.3 + labelScale * 1.5);
    }
    if (ring.current) {
      ring.current.rotation.z = time * 0.25;
      const m = ring.current.material as THREE.MeshBasicMaterial;
      m.opacity = 0.55 + 0.25 * Math.sin(time * 1.8);
    }
  });

  const labelH = 0.5;
  return (
    <group ref={group} position={def.pos} visible={false}>
      <mesh
        ref={core}
        geometry={sphereGeo}
        scale={def.radius}
        material={coreMat}
      />
      <sprite ref={halo} scale={def.radius * 5}>
        <spriteMaterial
          map={getRadialTexture()}
          color={base}
          transparent
          opacity={0.4}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
          toneMapped={false}
        />
      </sprite>
      <sprite ref={hotspot} scale={def.radius * 1.7}>
        <spriteMaterial
          map={getRadialTexture()}
          color={hotColor}
          transparent
          opacity={0.5}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
          toneMapped={false}
        />
      </sprite>
      {def.kind === "you" && (
        <mesh ref={ring} geometry={torusGeo} scale={def.radius} rotation={[Math.PI / 2.4, 0, 0]}>
          <meshBasicMaterial
            color={base}
            transparent
            opacity={0.6}
            toneMapped={false}
            side={THREE.DoubleSide}
          />
        </mesh>
      )}
      <sprite
        ref={label}
        position={[0, -(def.radius + 0.62), 0]}
        scale={[labelData.aspect * labelH, labelH, 1]}
        renderOrder={10}
      >
        <spriteMaterial
          map={labelData.tex}
          transparent
          opacity={0}
          depthTest={false}
          depthWrite={false}
        />
      </sprite>
      {altLabelData && (
        <sprite
          ref={altLabel}
          position={[0, -(def.radius + 1.18), 0]}
          scale={[altLabelData.aspect * labelH * 0.86, labelH * 0.86, 1]}
          renderOrder={10}
        >
          <spriteMaterial
            map={altLabelData.tex}
            transparent
            opacity={0}
            depthTest={false}
            depthWrite={false}
          />
        </sprite>
      )}
      <Moons def={def} pal={pal} />
    </group>
  );
}

/* ── 远景星云（把 CSS 辉光 token 带进 3D 空间） ── */

function Nebulas({ pal }: { pal: UniversePalette }) {
  return (
    <group>
      <sprite position={[-14, 7, -20]} scale={38}>
        <spriteMaterial
          map={getRadialTexture()}
          color={pal.glow1}
          transparent
          opacity={0.34}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
        />
      </sprite>
      <sprite position={[16, -5, -30]} scale={34}>
        <spriteMaterial
          map={getRadialTexture()}
          color={pal.glow2}
          transparent
          opacity={0.28}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
        />
      </sprite>
      <sprite position={[2, -9, 2]} scale={26}>
        <spriteMaterial
          map={getRadialTexture()}
          color={pal.glow1}
          transparent
          opacity={0.16}
          blending={THREE.AdditiveBlending}
          depthWrite={false}
        />
      </sprite>
    </group>
  );
}

/* ── 总装 ── */

export default function Constellation({ pal }: { pal: UniversePalette }) {
  return (
    <group>
      <Nebulas pal={pal} />
      {NODES.map((n) => (
        <NodeStar key={n.id} def={n} pal={pal} />
      ))}
      {EDGES.map((e) => (
        <Edge key={`${e.from}-${e.to}`} def={e} pal={pal} />
      ))}
      {EDGES.map((e, i) => (
        <Pulse key={`p-${e.from}-${e.to}`} def={e} pal={pal} phase={i * 0.37} />
      ))}
      {/* 辩论席第二发脉冲：交锋感 */}
      <Pulse
        def={EDGES.find((e) => e.kind === "debate") ?? EDGES[0]}
        pal={pal}
        phase={0.5}
      />
    </group>
  );
}
