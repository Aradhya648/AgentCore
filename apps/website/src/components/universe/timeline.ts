/**
 * 3D 沉浸官网（方案 C 原型）的叙事时间轴单一来源：
 * 章节文案、相机关键帧、滚动进度共享 store、进度网格全部定义在这里，
 * DOM 章节与 3D 场景都从此文件读，保证「文案讲到哪、画面演到哪」。
 *
 * 进度约定：p = scrollY / 最大可滚动高度 ∈ [0,1]。
 * 共 N 个满屏章节时，第 i 章标题居中可见的时刻恰为 p = i/(N-1)，
 * 因此所有出场时刻都锚定在 SEC(i) = i/(N-1) 网格上——
 * 「元素在其章节居中前就位，建造过程发生在滚入途中」。
 */

export type SectionDef = {
  id: string;
  eyebrow: string;
  title: string;
  /** 标题里需要渐变强调的第二行（可选） */
  titleAccent?: string;
  body: string;
  align: "left" | "right" | "center";
};

export const SECTIONS: SectionDef[] = [
  {
    id: "hero",
    eyebrow: "AgentCore · 协作智能平台",
    title: "协作，",
    titleAccent: "是更高级的智能",
    body: "向下滚动——看一支 AI 团队如何在你眼前诞生。",
    align: "center",
  },
  {
    id: "alone",
    eyebrow: "为什么需要一支团队",
    title: "一个再聪明的助手，",
    titleAccent: "也只是一个人在战斗",
    body: "单个模型的智能有天花板。它自己出题、自己答、自己打分——没有人质疑它的结论，没有人替它把关。",
    align: "left",
  },
  {
    id: "goal",
    eyebrow: "01 · 你下达目标",
    title: "你只说要什么，",
    titleAccent: "其余交给团队",
    body: "一句自然语言的目标，CEO 主 Agent 即刻理解任务、组建团队、分配角色与工具、定下依赖关系。",
    align: "right",
  },
  {
    id: "waves",
    eyebrow: "02 · 团队分波推进",
    title: "能并行的并行，",
    titleAccent: "需衔接的衔接",
    body: "调度器按依赖关系把任务编成波次：多个 Agent 同时开工，产物在共享工作区流转，彼此协商、互通情报。",
    align: "left",
  },
  {
    id: "debate",
    eyebrow: "03 · 辩论与互审",
    title: "有人交锋，",
    titleAccent: "才有可信的结论",
    body: "关键决策正反辩论，产出交叉互审。结论不是一家之言，而是被质检过的共识。",
    align: "right",
  },
  {
    id: "visible",
    eyebrow: "04 · 全程可见",
    title: "每一步都看得见，",
    titleAccent: "你随时拍板",
    body: "谁在做什么、为什么这样决策、花了多少成本——一张作战图尽收眼底。需要你决断时，团队会带着现场来找你。",
    align: "left",
  },
  {
    id: "finale",
    eyebrow: "AI 的下一步",
    title: "不是更聪明的个体，",
    titleAccent: "而是更好的协作。",
    body: "AgentCore——让 AI 像团队一样工作。",
    align: "center",
  },
];

export const SECTION_COUNT = SECTIONS.length;

/** 第 i 章标题居中可见时的全局进度 */
export const SEC = (i: number) => i / (SECTION_COUNT - 1);

/* ── 滚动进度共享 store（模块级单例，避免每帧 React 重渲） ── */

export const progressStore = {
  /** 全局滚动进度 0..1 */
  value: 0,
  /** 立即快进（截图/锚点跳转用）：相机与出场动画跳过阻尼 */
  snap: false,
  reducedMotion: false,
};

/* ── 缓动工具 ── */

export function clamp01(x: number): number {
  return x < 0 ? 0 : x > 1 ? 1 : x;
}

export function smoothstep(x: number): number {
  const t = clamp01(x);
  return t * t * (3 - 2 * t);
}

/** 在 [start, end] 进度窗口内的 0..1 出场量（带平滑） */
export function windowProgress(p: number, start: number, end: number): number {
  return smoothstep((p - start) / (end - start));
}

/* ── 相机旅程：每章一个关键帧，段内 smoothstep 插值 ── */

export type CameraKey = {
  pos: [number, number, number];
  look: [number, number, number];
};

export const CAMERA_KEYS: CameraKey[] = [
  { pos: [0, 0.4, 25.5], look: [0, -3.1, 8] }, // hero：孤星悬于标题上方
  { pos: [3.4, 1.2, 15.5], look: [-1.4, 0.3, 8] }, // alone：孤星让出左侧面板位
  { pos: [6.2, 1.8, 18.2], look: [2.4, -0.1, 10.6] }, // goal：你+CEO 居左，右侧留白
  { pos: [10.5, 5, 7.5], look: [-4.6, -0.6, -4] }, // waves：拉远看两波团队（居右）
  { pos: [5.5, 2.2, -6.5], look: [3.2, 1.2, -14.5] }, // debate：辩论席居左
  { pos: [12.5, 16, 1.5], look: [-1.7, -1, -5.5] }, // visible：升空俯瞰全图（居右）
  { pos: [16, 9, 18], look: [-4.2, 0.4, -5.5] }, // finale：全景移到面板右侧与上方
];

export function cameraAt(p: number): {
  pos: [number, number, number];
  look: [number, number, number];
} {
  const segCount = CAMERA_KEYS.length - 1;
  const x = clamp01(p) * segCount;
  const i = Math.min(Math.floor(x), segCount - 1);
  const t = smoothstep(x - i);
  const a = CAMERA_KEYS[i];
  const b = CAMERA_KEYS[i + 1];
  const lerp = (m: number, n: number) => m + (n - m) * t;
  return {
    pos: [
      lerp(a.pos[0], b.pos[0]),
      lerp(a.pos[1], b.pos[1]),
      lerp(a.pos[2], b.pos[2]),
    ],
    look: [
      lerp(a.look[0], b.look[0]),
      lerp(a.look[1], b.look[1]),
      lerp(a.look[2], b.look[2]),
    ],
  };
}

/* ── 进度网格速查（N=7 → 间隔 1/6 ≈ 0.1667） ──
 * hero 0 · alone 0.167 · goal 0.333 · waves 0.5 ·
 * debate 0.667 · visible 0.833 · finale 1.0
 */
