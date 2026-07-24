import type { SidecarTarget } from "@/services/sidecarRouting";
import { takeRecentSidecarFailure } from "@/services/sidecarStatus";

/**
 * 本地引擎（sidecar）会话级健康缓存 + 主动探活。
 *
 * 双模式工作区 §一.1 / 本地引擎毕业 · 探活增强。本地引擎毕业到**默认开**后，所有绑本机本地
 * 文件夹的对话都会走 sidecar——若用户机器环境起不来（杀软拦截 / 缺组件 / venv 损坏…），没有
 * 探活则每个回合都要「试 startTurn → 启动失败 → 降级回云端（阶段二）→ 弹一次提示」，反复打扰。
 *
 * 本模块把「首轮失败」前移成一次**主动探活**，并按 `root + subpath` 记住结果（app 进程内、
 * 会话级，不持久化）：
 *   - {@link probeSidecar}：首次走 sidecar 前调；未知则拉起进程 + initialize 握手（不跑回合）验
 *     证环境，成功标 `ok` / 失败标 `bad`（诊断取自 `sidecarStatus`）。已有结论则直接返回、不重探；
 *     返回的 `probed` 区分「本次真探活」与「命中缓存」，让调用方只在首探失败时提示一次。
 *   - {@link getSidecarHealth}：查询本会话对某根的健康结论（`ok`/`bad`/`unknown`），供测试断言 /
 *     UI 状态展示。路由判定（`resolveSidecarRoot`）**不**看它——健康收敛由各调用方按语义处理
 *     （`sendTurn` 探活失败走云、`runResume` 探活失败保留帧），见各处。
 *   - {@link markSidecarUnhealthy}：阶段二降级（探活通过、但回合启动期仍失败的边缘）也标 `bad`，
 *     与探活**共用**同一「记坏 → 命中缓存」出口，不形成第二条降级路径。
 *   - {@link clearSidecarHealth}：用户在设置里重新开启本地引擎时清空，给「修好环境后重试」机会。
 *
 * 探活成功留存的进程正好被随后的首个回合复用（主进程 `ensure` 命中缓存），故探活不浪费拉起。
 */

type Health = "ok" | "bad";

/** `rootId::subpath` → 本会话探明的健康（与主进程 `entryKey` 同构）。无项 = 未探活（unknown）。 */
const health = new Map<string, Health>();

function keyOf(target: SidecarTarget): string {
  return `${target.rootId}::${target.subpath}`;
}

/** 本会话对某 sidecar 目标的健康结论：`ok` 可走 / `bad` 跳过走云 / `unknown` 尚未探活。 */
export function getSidecarHealth(target: SidecarTarget): Health | "unknown" {
  return health.get(keyOf(target)) ?? "unknown";
}

/**
 * 标记某 sidecar 目标本会话「环境起不来」（探活失败、或阶段二降级的边缘失败）。
 *
 * 标记后 `probeSidecar` 对该根命中 `bad` 缓存（`probed:false`），故同一坏环境只在首轮提示一次、
 * 后续新回合静默走云。
 */
export function markSidecarUnhealthy(target: SidecarTarget): void {
  health.set(keyOf(target), "bad");
}

/** 清空全部健康结论（用户在设置里重新开启本地引擎时调，允许对坏过的根重新探活）。 */
export function clearSidecarHealth(): void {
  health.clear();
}

/** 一次探活的结论：是否健康 + 本次是否真探活（区分首探 / 命中缓存）+ （失败时）可读诊断。 */
export interface SidecarProbeOutcome {
  healthy: boolean;
  /** 本次是否真执行了探活（true = 首探；false = 命中 `ok`/`bad` 缓存或非桌面）。调用方据此
   * 「只在首探失败时提示一次」——缓存 `bad` 命中静默走云、不再打扰。 */
  probed: boolean;
  detail: string | null;
}

/**
 * 探活一个 sidecar 目标（带会话级缓存）：未知则主动拉起 + 握手验证环境，已有结论则直接返回。
 *
 * 成功 → 标 `ok`、返回 healthy（留存的进程被随后首个回合复用）；失败 → 标 `bad`、返回带诊断的
 * unhealthy（诊断取自 `sidecarStatus` 的 onStatus 推送）。非桌面 / 未注入 `sidecarApi` 时视作
 * 不健康（调用方退回云链路）。`probed` 标本次是否真探活：缓存命中（`ok`/`bad`）/ 非桌面均 `false`，
 * 让调用方对缓存 `bad` 静默走云、只在首探（`probed:true`）失败时提示一次。
 */
export async function probeSidecar(
  target: SidecarTarget,
): Promise<SidecarProbeOutcome> {
  const cached = health.get(keyOf(target));
  if (cached === "ok") return { healthy: true, probed: false, detail: null };
  if (cached === "bad") return { healthy: false, probed: false, detail: null };

  if (typeof window === "undefined" || !window.sidecarApi) {
    return { healthy: false, probed: false, detail: null };
  }
  try {
    await window.sidecarApi.probe({
      rootId: target.rootId,
      subpath: target.subpath,
    });
    health.set(keyOf(target), "ok");
    return { healthy: true, probed: true, detail: null };
  } catch {
    health.set(keyOf(target), "bad");
    // 诊断由主进程 onStatus(error) 推入 sidecarStatus；取走它换出针对性提示（取不到则 null，
    // 由调用方退回通用兜底文案）。
    return {
      healthy: false,
      probed: true,
      detail: takeRecentSidecarFailure(target.rootId),
    };
  }
}
