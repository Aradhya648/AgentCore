import type { LogLevel } from "@shared/log-contract";

/**
 * 渲染层结构化日志入口。把事件交给主进程（经 preload 的 `window.logApi`）落到产品日志
 * `userData/logs/desktop.jsonl`——主进程会自动补 `timestamp` / `build`(prod|dev) /
 * `version`。契约与动机见 `@shared/log-contract`。
 *
 * 无 preload 的环境（纯浏览器预览 / 单测）`window.logApi` 缺失，回退到 console，**永不抛错**
 * （日志失败绝不能影响业务流）。铁律：禁止把 token / 密码 / 消息正文放进 `fields`。
 */
export function logEvent(
  level: LogLevel,
  event: string,
  fields?: Record<string, unknown>,
): void {
  try {
    const api = typeof window !== "undefined" ? window.logApi : undefined;
    if (api) {
      api.write({ level, event, fields });
      return;
    }
  } catch {
    /* 落 preload 失败——回退 console */
  }
  const tag = `[${event}]`;
  if (level === "error") console.error(tag, fields ?? {});
  else if (level === "warn") console.warn(tag, fields ?? {});
  else console.info(tag, fields ?? {});
}
