/**
 * 全局搜索结果过滤（时间维度）的纯逻辑（搜索结果过滤 · 方向 4）。
 *
 * 命令面板把用户选中的时间档位转成后端 `updated_after` 的 ISO 边界。此处独立成纯
 * 函数以便注入 `now` 做确定性单测（面板本身只做取值 + 传参）。项目维度是一个
 * folder id，无需换算，故不在此。
 */

/** 时间过滤档位：全部 / 今天（本地零点起）/ 近 7 天 / 近 30 天（滚动窗口）。 */
export type TimeFilter = "all" | "today" | "7d" | "30d";

/** 档位渲染顺序（也用于分段控件）。 */
export const TIME_FILTER_ORDER: readonly TimeFilter[] = [
  "all",
  "today",
  "7d",
  "30d",
] as const;

/** 各档位的中文短标签。 */
export const TIME_FILTER_LABELS: Record<TimeFilter, string> = {
  all: "全部时间",
  today: "今天",
  "7d": "近 7 天",
  "30d": "近 30 天",
};

const DAY_MS = 24 * 60 * 60 * 1000;

/**
 * 把时间档位换算成后端 `updated_after` 的 ISO 边界；「全部」返回 `undefined`（不加约束）。
 *
 * 「今天」= 本地零点起（用户直觉上的「今天」，非滚动 24h）；「近 N 天」= 从此刻回溯 N×24h
 * 的滚动窗口。`now` 可注入以便单测。
 */
export function timeFilterSince(
  filter: TimeFilter,
  now: Date = new Date(),
): string | undefined {
  switch (filter) {
    case "all":
      return undefined;
    case "today": {
      const midnight = new Date(now);
      midnight.setHours(0, 0, 0, 0);
      return midnight.toISOString();
    }
    case "7d":
      return new Date(now.getTime() - 7 * DAY_MS).toISOString();
    case "30d":
      return new Date(now.getTime() - 30 * DAY_MS).toISOString();
  }
}
