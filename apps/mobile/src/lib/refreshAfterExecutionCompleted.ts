/**
 * `execution_completed` 后的最小刷新：reload 最新消息窗以拉入 harvest 合成用户消息 + CEO 终稿。
 *
 * 对齐桌面语义（短延迟重试），实现走手机现有 `getMessages` 通道——不引入桌面 store。
 * `execution_completed` 早于 harvest 落库，故 0 / 1.5s / 6s 覆盖收口回合写完窗口；
 * 离开会话由调用方 cancel（与 memory poll 同款 gen 门闩）。
 */

export const HARVEST_REFRESH_DELAYS_MS = [0, 1500, 6000] as const;

/** `isCurrent` 在 await 后仍须为真，才可写回 UI（防切会话竞态）。 */
export type HarvestReload = (
  conversationId: string,
  isCurrent: () => boolean,
) => Promise<void>;

export type HarvestRefreshScheduler = {
  /** 收到 `execution_completed` 时调用：立刻 + 延迟重试 reload。 */
  schedule: (conversationId: string) => void;
  /** 切换 / 卸载会话时作废未完成的重试。 */
  cancel: () => void;
};

/**
 * 宿主回合已 `message_end`（含 detached 提前收口）后，其内容会进 REST 窗；
 * 丢弃这些已落盘 live turn，避免与 history 双份。未收口的 mid-flight turn2 保留。
 */
export function dropSettledLiveTurns<T extends { events: { type: string }[] }>(
  turns: T[],
): T[] {
  return turns.filter(
    (turn) => !turn.events.some((e) => e.type === "message_end"),
  );
}

export function createHarvestRefreshScheduler(
  reload: HarvestReload,
  delays: readonly number[] = HARVEST_REFRESH_DELAYS_MS,
): HarvestRefreshScheduler {
  let gen = 0;

  const run = (conversationId: string, myGen: number): void => {
    if (myGen !== gen) return;
    void reload(conversationId, () => myGen === gen).catch(() => {
      /* best-effort — 离开再进仍走正常加载 */
    });
  };

  return {
    schedule(conversationId: string) {
      const myGen = ++gen;
      for (const ms of delays) {
        if (ms <= 0) {
          run(conversationId, myGen);
        } else {
          setTimeout(() => run(conversationId, myGen), ms);
        }
      }
    },
    cancel() {
      gen += 1;
    },
  };
}
