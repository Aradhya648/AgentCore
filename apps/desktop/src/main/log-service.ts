/**
 * 桌面端产品日志（主进程落盘）—— renderer 经 `app:log` IPC 把结构化事件交来，这里按
 * **JSON Lines** 追加到 `userData/logs/desktop.jsonl`，并自动补 `timestamp` /
 * `build`(prod|dev) / `version`。契约与动机见 `@shared/log-contract`。
 *
 * 设计要点：
 * - **best-effort**：任何写盘/序列化失败都吞掉——日志绝不能把主流程带崩。
 * - **有序**：所有写经一个 promise 队列串行化，避免并发 append 交错。
 * - **有界**：单文件超 `MAX_BYTES` 即滚动到 `.1`（仅留一个备份，磁盘占用封顶 2 份）。
 * - **dev 镜像**：未打包态额外打到 stdout，`pnpm dev` 终端直接可见。
 */

import { appendFile, mkdir, rename, stat } from "node:fs/promises";
import { join } from "node:path";
import {
  LOG_CHANNELS,
  type LogEntry,
  type LogLevel,
  type LogRecord,
} from "@shared/log-contract";
import { app, ipcMain } from "electron";

// 5MB 后滚动到单个 `.jsonl.1` 备份——产品日志事件稀疏，足够覆盖问题窗口又不撑爆磁盘。
const MAX_BYTES = 5 * 1024 * 1024;

let logDir: string | null = null;
let logFile: string | null = null;
let dirReady = false;
// 写队列：串行化 append，保证落盘顺序、互不交错。
let queue: Promise<void> = Promise.resolve();
// 内存里的体积估计，避免每行 stat()；首次写时从磁盘惰性播种。
let bytes = -1;

function paths(): { dir: string; file: string } {
  if (!logDir || !logFile) {
    logDir = join(app.getPath("userData"), "logs");
    logFile = join(logDir, "desktop.jsonl");
  }
  return { dir: logDir, file: logFile };
}

/** 防御性归一：IPC 来的 entry 可能畸形——给 level/event 兜底，丢弃非对象 fields。 */
function sanitize(entry: LogEntry | null | undefined): LogEntry {
  const lvl = entry?.level;
  const level: LogLevel =
    lvl === "debug" || lvl === "warn" || lvl === "error" ? lvl : "info";
  const event =
    typeof entry?.event === "string" && entry.event ? entry.event : "unknown";
  const fields =
    entry?.fields && typeof entry.fields === "object"
      ? entry.fields
      : undefined;
  return { level, event, fields };
}

function toRecord(entry: LogEntry): LogRecord {
  return {
    timestamp: new Date().toISOString(),
    build: app.isPackaged ? "prod" : "dev",
    version: app.getVersion(),
    ...entry,
  };
}

async function rollIfNeeded(file: string, addLen: number): Promise<void> {
  if (bytes < 0) {
    try {
      bytes = (await stat(file)).size;
    } catch {
      bytes = 0; // 尚未创建
    }
  }
  if (bytes + addLen > MAX_BYTES) {
    try {
      await rename(file, `${file}.1`); // 覆盖旧 .1——封顶 2 份
    } catch {
      /* 首次运行无可滚动——忽略 */
    }
    bytes = 0;
  }
}

async function writeRecord(record: LogRecord): Promise<void> {
  const { dir, file } = paths();
  const line = `${JSON.stringify(record)}\n`;
  if (!dirReady) {
    await mkdir(dir, { recursive: true });
    dirReady = true;
  }
  await rollIfNeeded(file, line.length);
  await appendFile(file, line, "utf8");
  bytes += line.length;
}

/**
 * 落一条结构化日志到产品日志文件（best-effort）。主进程自身与 renderer（经 IPC）共用。
 * 失败静默吞掉；dev 态额外镜像到 stdout。
 */
export function logDesktop(entry: LogEntry): void {
  const record = toRecord(sanitize(entry));
  if (!app.isPackaged) {
    // stdout/stderr 可能已断开（父进程关了终端、管道被掐）——console.* 写时会同步抛
    // EPIPE；必须吞掉，否则会变成主进程 Uncaught Exception 弹窗，违背 best-effort。
    try {
      const tag = `[${record.build}] ${record.event}`;
      if (record.level === "error") console.error(tag, record.fields ?? {});
      else if (record.level === "warn") console.warn(tag, record.fields ?? {});
      else console.log(tag, record.fields ?? {});
    } catch {
      /* EPIPE / 其它流错误——忽略 */
    }
  }
  queue = queue.then(() => writeRecord(record)).catch(() => {});
}

/**
 * 注册渲染层日志通道（`app:log`，单向 send）。在 `app.whenReady` 内调用一次。
 * 用 `.on` 而非 `.handle`：日志是 fire-and-forget，renderer 不等回执、失败不阻塞 UI。
 */
export function registerLogIpc(): void {
  ipcMain.on(LOG_CHANNELS.write, (_event, entry: LogEntry) =>
    logDesktop(entry),
  );
}
