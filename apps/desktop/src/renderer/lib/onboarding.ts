/**
 * 新用户首启体验 — 草稿空态与情境提示的纯客户端决策与本地持久化。
 *
 * 平台代付、开箱即用：不存在「先接入模型才能对话」的门。首启入口 = 草稿空态
 *（starter chips / returning），判定不依赖服务端状态 / DB；情境提示 seen
 * 一律走 {@link uiStorage}。BYOK 降级为「设置·模型配置」里的可选升级。
 */

import { uiGet, uiSet } from "@/lib/uiStorage";

/** 情境提示 id（总量 ≤3，各只出现一次）。 */
export type ContextualTipId = "inline_team_graph";

const TIP_KEY_PREFIX = "onboarding:tip:";

export function tipStorageKey(id: ContextualTipId): string {
  return `${TIP_KEY_PREFIX}${id}`;
}

/** 草稿页空态两态（平台代付后无「未接入」态）。 */
export type DraftEmptyKind = "starter_chips" | "returning";

export type DraftEmptyInput = {
  conversationCount: number;
};

/** 草稿空态（无消息）两态选择。首个对话产生后 starter chips 永久消失。 */
export function resolveDraftEmptyKind(input: DraftEmptyInput): DraftEmptyKind {
  if (input.conversationCount === 0) return "starter_chips";
  return "returning";
}

/**
 * 空草稿态是否把对话输入框与引导合成视口中央块。
 * 「（草稿态 ∨ 已落库但确定 0 消息）∧ 无消息」——平台代付后 keyless 亦居中，无接入门例外。
 *
 * `isDraft`（`conversationId === null`）是主闸门：已落库的对话切换时会先经历一个
 * 「消息尚未异步加载完」的空窗口，若只看 `!hasMessages` 会把它误判为居中欢迎态，
 * 导致输入框「先弹到中间、加载完再飞回底栏」的跳动。
 *
 * `knownEmptyPersisted` 覆盖「演示磁带 prepare 绑定的空会话」这类**已落库却确定 0 消息**的场景：
 * 它由会话元数据 `messageCount === 0` 推出——确定为空、无需等历史异步加载，故不会重蹈上述抖动
 * （有消息的会话 messageCount>0、历史加载中未入列表的会话元数据查不到，二者皆不命中）。
 */
export function shouldCenterDraftComposer(input: {
  isDraft: boolean;
  hasMessages: boolean;
  knownEmptyPersisted?: boolean;
}): boolean {
  if (input.hasMessages) return false;
  return input.isDraft || input.knownEmptyPersisted === true;
}

/** 首启任务建议 — 天然触发多 Agent 分工；点击仅填入输入框。 */
export const STARTER_TASK_CHIPS: readonly string[] = [
  "分三路并行调研：竞品定价、用户痛点、渠道策略，各自产出一页摘要后由你汇总成决策简报。",
  "请拉一位写手起草产品介绍初稿，一位审校挑逻辑漏洞，一位整理成对外可用的发布说明。",
  "帮我规划一次周末短途旅行：一人查交通与住宿，一人排景点与用餐，最后合成一份可执行行程。",
] as const;

export function hasSeenTip(id: ContextualTipId): boolean {
  return uiGet<boolean>(tipStorageKey(id)) === true;
}

export function markTipSeen(id: ContextualTipId): void {
  uiSet(tipStorageKey(id), true);
}

/** 是否应展示某条情境提示（未 seen 才展示）。 */
export function shouldShowTip(id: ContextualTipId): boolean {
  return !hasSeenTip(id);
}
