/**
 * 桌面端结构化日志 IPC 契约 —— 主进程 / preload / renderer 三端共享的单一真相源。
 *
 * 渲染层在沙箱里无法直接落盘，故经此通道把结构化事件交给主进程，由主进程按 **JSON
 * Lines** 追加到 `userData/logs/desktop.jsonl`（与后端 `logs/dev.jsonl` 同为可被
 * `json.loads` / `jq` 逐行解析的产品日志）。每行由主进程自动补 `timestamp` /
 * `build`(prod|dev) / `version`——这让产品日志**真正能区分「安装版」与「开发态」**：
 * 开发态会出现 `auth.bootstrap result=dev_auto_login`（被 .env.local 自动重登掩盖的那条
 * 路径），生产态则只会是 me_ok / refreshed / logged_out / outage。
 *
 * 事件命名沿用后端「组件.动作」式（如 `auth.bootstrap`），动作/状态走 snake_case 字段。
 * 鉴权可观测：`auth.bootstrap`（冷启动）、`auth.refresh`（静默刷新失败/歧义 cookie）、
 * `auth.session_kicked`（中途踢回登录页）。
 * 铁律：禁止把 token / 密码 / 消息正文放进 `fields`（只记可观测信号，不记机密与正文）。
 *
 * 与 ipc-contract（文件系统）/ sidecar-contract（本地引擎）/ updater-contract（自动更新）
 * 分文件：各自独立的主进程能力，刻意不混在一个契约里。
 */

export type LogLevel = "debug" | "info" | "warn" | "error";

/** renderer 发往主进程的一条日志（fire-and-forget，不等回执）。 */
export interface LogEntry {
  level: LogLevel;
  /** 组件.动作，如 `auth.bootstrap`。 */
  event: string;
  /** 结构化字段（已脱敏：禁止放 token / 密码 / 消息正文）。 */
  fields?: Record<string, unknown>;
}

/** 主进程落盘后每行的最终形状（在 {@link LogEntry} 基础上补运行环境元数据）。 */
export interface LogRecord extends LogEntry {
  /** ISO 8601 UTC 时间戳。 */
  timestamp: string;
  /** 安装版（打包）= "prod"；dev / 未打包 = "dev"——产品日志据此区分本机与开发。 */
  build: "prod" | "dev";
  /** 应用版本（`app.getVersion()`）。 */
  version: string;
}

/** IPC 通道名 —— 主进程与 preload 共用，避免硬编码漂移（对齐 fs/sidecar/updater 契约写法）。 */
export const LOG_CHANNELS = {
  /** renderer → main，单向 send（fire-and-forget，日志失败绝不回灌阻塞 UI）。 */
  write: "app:log",
} as const;

/** 暴露在 `window.logApi` 上的 renderer 端 API 面。 */
export interface LogApi {
  /** 记一条结构化日志到产品日志文件（fire-and-forget；失败静默吞掉）。 */
  write(entry: LogEntry): void;
}
