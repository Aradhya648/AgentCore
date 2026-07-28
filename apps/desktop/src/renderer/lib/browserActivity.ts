/**
 * L3「团队浏览器」tab 的**存在性判定**（纯派生，指针非副本）——「本会话曾用过浏览器」。
 *
 * 右坞「浏览器」tab 走**条件常驻**（同「终端」tab 先例，见 `shouldShowTerminalTab`）：本会话
 * 出现过 `browser_*` 工具调用 → tab 常驻整个会话，而不是「有直播目标才出现、用完即消失」。
 * 动因是两个窗口原本相反——接管默认**仅无 turn 运行时**可做，而旧入口（活动卡「查看直播」）
 * 只在 turn `running` 时渲染：用户必须在跑的时候先点开 tab 才能在停下后接管，没提前点开就
 * 再无入口，而此时沙箱还活着（idle TTL）、页面状态还在，正是最该上手的时刻。
 *
 * 判定只扫 execution 投影的 `agent.toolCalls`——`browser_*` 契约上 **worker-only**
 * （`surface=worker_only`，见 `docs/03-AI核心/工具与能力系统.md`），CEO 直调不存在，故
 * `message.process` 一律不扫。**若哪天浏览器工具开放给 CEO 直调，这里要一并加 process 侧**
 * （否则 tab 不出现）；不预留半通的防御分支。
 *
 * 本地模式：sidecar 在 DesktopBrowserBridge 健康时装配 `browser_*`
 * （`browser_execution_enabled_for`：local + `AGENTCORE_BROWSER_BRIDGE_*` 探活）；
 * Bridge 未注入/不健康则不挂工具。
 */

import { assistantProjectionId } from "@/stores/conversation/runtime";
import type { Message } from "@/stores/conversation/types";
import { type ExecutionRuntime, projectRuntime } from "@/stores/execution";

/** 是否 L3 团队浏览器工具（`browser_*` 六工具）。工具名判定单源，勿另写一份前缀比较。 */
export function isBrowserTool(name: string): boolean {
  return name.startsWith("browser_");
}

/**
 * 本会话是否**曾有**浏览器活动（→ 右坞「浏览器」tab 是否显示）。
 *
 * `executionById` 以 `assistantProjectionId` 为键（与 sidePanel / 终端 tab 判定同一坐标系）；
 * `projectRuntime` 按 rt 快照 WeakMap 缓存，故本判定可安全放进 zustand 选择器逐 tick 跑
 * （返回布尔 → 流式 token 期间不触发右坞重渲染，见 SidePanel 的收窄订阅纪律）。
 */
export function conversationHasBrowserActivity(
  messages: Message[],
  executionById: Record<string, ExecutionRuntime>,
): boolean {
  for (const msg of messages) {
    if (msg.role !== "assistant") continue;
    const rt = executionById[assistantProjectionId(msg)];
    if (!rt) continue;
    const exec = projectRuntime(rt);
    if (!exec) continue;
    for (const agent of exec.agents) {
      if (agent.toolCalls.some((tc) => isBrowserTool(tc.toolName))) return true;
    }
  }
  return false;
}

/**
 * 本会话是否存在 pending 的 `browserLogin` escalate（→ 归还控制提示走登录口径）。
 * 与 EscalationCard「需要你登录」同源：扫 execution 投影 `run.escalations`，
 * 勿硬编码接管原因。
 */
export function conversationHasPendingBrowserLogin(
  messages: Message[],
  executionById: Record<string, ExecutionRuntime>,
): boolean {
  for (const msg of messages) {
    if (msg.role !== "assistant") continue;
    const rt = executionById[assistantProjectionId(msg)];
    if (!rt) continue;
    const exec = projectRuntime(rt);
    if (!exec) continue;
    for (const run of exec.runs) {
      if (
        run.escalations.some(
          (e) => e.status === "pending" && e.browserLogin === true,
        )
      ) {
        return true;
      }
    }
  }
  return false;
}

/**
 * 本会话是否有 turn / execution 在跑（→ 接管闸「turn_running」前端对齐）。
 * 扫本会话 assistant 消息的 execution 投影 `status === "running"`，与后端
 * `_running(conversation_id)`（turn_runs 未完成）同语义坐标系——勿另发明
 * `isStreaming` / `hasUnsettledRuns` 等旁路。
 */
export function conversationHasRunningTurn(
  messages: Message[],
  executionById: Record<string, ExecutionRuntime>,
): boolean {
  for (const msg of messages) {
    if (msg.role !== "assistant") continue;
    const rt = executionById[assistantProjectionId(msg)];
    if (!rt) continue;
    const exec = projectRuntime(rt);
    if (exec?.status === "running") return true;
  }
  return false;
}
