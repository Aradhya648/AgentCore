import type { SidecarStatusPush } from "@shared/sidecar-contract";

/**
 * 消费 sidecar 生命周期 / 诊断推送（接通 `onStatus` 死通道）。
 *
 * 双模式工作区 / 远期规划 §一.1：sidecar（本机 Python 引擎）拉起失败 / 进程退出会经主进程
 * `onStatus` 推来**精确诊断**（uv/venv 找不到、引擎导入失败、退出码…）。在此之前 renderer
 * 无任何消费方——一个 sidecar 回合失败只体现为通用「网络连接中断」横幅，把「本地引擎起不来」
 * 误报成「网络问题」，既误导又无从排查。
 *
 * 本服务订阅该通道、按本地根记下**最近一次**失败诊断，供 `streamConversationViaSidecar` 在
 * 回合失败时换出**针对性**横幅（而非通用 network）。一次健康拉起（`spawned`）会清掉该根的陈旧
 * 失败记录，避免一次旧故障污染后续无关的回合。
 */

interface SidecarFailure {
  phase: "error" | "exited";
  detail: string;
  at: number;
}

/** rootId → 最近一次失败诊断（`spawned` 清除、被取走即删——见下）。 */
const failures = new Map<string, SidecarFailure>();
let installed = false;

/**
 * 订阅 `onStatus`（幂等）；在 renderer 启动时调一次。
 *
 * 非桌面环境 / 未注入 `window.sidecarApi`（如纯 web 预览、单测）时 no-op，故调用方无需自行
 * 守卫。订阅只增不减（renderer 生命周期 = app 生命周期），无需返回退订函数。
 */
export function installSidecarStatusListener(): void {
  if (installed) return;
  if (typeof window === "undefined" || !window.sidecarApi) return;
  installed = true;
  window.sidecarApi.onStatus(recordStatus);
}

/**
 * 记录一条 status 推送（也是单测注入点，绕开 IPC）。
 *
 * `spawned` 视作该根恢复健康 → 清掉陈旧失败；`error` / `exited` 覆盖记录为最近失败。
 */
export function recordStatus(push: SidecarStatusPush): void {
  if (push.phase === "spawned") {
    failures.delete(push.rootId);
    return;
  }
  failures.set(push.rootId, {
    phase: push.phase,
    detail: (push.detail ?? "").trim() || defaultDetail(push.phase),
    at: Date.now(),
  });
}

/** 一次失败记录被视为「能解释刚失败的回合」的有效期：超期的陈旧诊断不再套用（防误标）。 */
const FAILURE_TTL_MS = 15_000;

/**
 * 取走某根最近一次 sidecar 失败诊断（够新才返回），用于解释一个**刚刚**失败的回合。
 *
 * 一次性消费（取走即删）：同一条诊断只解释一个回合，绝不渗到之后无关的失败里。返回已是
 * 用户可读的中文短句（含「启动失败 / 进程退出」语境 + 主进程给的 `detail`）；无最近失败或
 * 已超期则返回 `null`，由调用方退回更弱的兜底文案。
 */
export function takeRecentSidecarFailure(rootId: string): string | null {
  const f = failures.get(rootId);
  if (!f) return null;
  failures.delete(rootId);
  if (Date.now() - f.at > FAILURE_TTL_MS) return null;
  return f.phase === "exited"
    ? `本地引擎进程已退出：${f.detail}`
    : `本地引擎启动失败：${f.detail}`;
}

function defaultDetail(phase: "error" | "exited"): string {
  return phase === "exited" ? "进程已退出" : "启动失败";
}
