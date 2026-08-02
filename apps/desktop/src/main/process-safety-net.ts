/**
 * 主进程安全网：吞掉 Chromium / Node 网络瞬态错误，避免 Electron 默认弹出
 * “A JavaScript error occurred in the main process”（打包态 electron-updater /
 * net.fetch 对端关连接时常见）。非网络未捕获异常记日志后退出——主进程未知
 * 异常后继续跑不安全（Electron 文档建议）。
 *
 * 本模块在 index 中必须作为**首个** import，并在加载时自注册。
 */
import { app } from "electron";

const NET_ERR_RE = /net::ERR_[A-Z0-9_]+/i;

const NODE_TRANSIENT_CODES = new Set([
  "ECONNRESET",
  "ECONNREFUSED",
  "ECONNABORTED",
  "ENOTFOUND",
  "ETIMEDOUT",
  "EPIPE",
  "ENETUNREACH",
  "EHOSTUNREACH",
  "EAI_AGAIN",
  "ENETDOWN",
]);

function errorText(error: unknown): string {
  if (error instanceof Error) return error.message;
  if (typeof error === "string") return error;
  if (error == null) return "";
  try {
    return String(error);
  } catch {
    return "";
  }
}

function errorCode(error: unknown): string {
  if (!error || typeof error !== "object") return "";
  if (!("code" in error)) return "";
  const code = (error as { code?: unknown }).code;
  return typeof code === "string" || typeof code === "number"
    ? String(code)
    : "";
}

/** Chromium `net::ERR_*` 或常见 Node 网络 errno —— 可恢复，不弹框、不退出。 */
export function isTransientNetworkError(error: unknown): boolean {
  const text = errorText(error);
  if (NET_ERR_RE.test(text)) return true;
  // 少数路径只抛裸 `ERR_CONNECTION_CLOSED`（无 net:: 前缀）
  if (
    /\bERR_(CONNECTION_|NAME_NOT_RESOLVED|INTERNET_DISCONNECTED|TIMED_OUT|NETWORK_CHANGED|ADDRESS_UNREACHABLE|CONNECTION_RESET|CONNECTION_REFUSED|CONNECTION_TIMED_OUT|EMPTY_RESPONSE|SSL_PROTOCOL_ERROR)/i.test(
      text,
    )
  ) {
    return true;
  }
  return NODE_TRANSIENT_CODES.has(errorCode(error));
}

let installed = false;
let exiting = false;

/** Graceful quit first; hard-exit if the process is still alive after this. */
const FATAL_QUIT_GRACE_MS = 2500;

function hardExit(): void {
  try {
    app.exit(1);
  } catch {
    process.exit(1);
  }
}

function exitAfterFatal(kind: string, error: unknown): void {
  console.error(`[main] ${kind}:`, error);
  if (exiting) return;
  exiting = true;
  try {
    app.quit();
  } catch {
    // quit unavailable / throws — still schedule hard exit below
  }
  const timer = setTimeout(hardExit, FATAL_QUIT_GRACE_MS);
  // Don't keep the process alive solely for the grace timer.
  timer.unref?.();
}

export function installProcessSafetyNet(): void {
  if (installed) return;
  installed = true;

  process.on("uncaughtException", (error) => {
    if (isTransientNetworkError(error)) {
      console.error("[main] transient network error (ignored):", error);
      return;
    }
    exitAfterFatal("uncaughtException", error);
  });

  process.on("unhandledRejection", (reason) => {
    if (isTransientNetworkError(reason)) {
      console.error("[main] transient network rejection (ignored):", reason);
      return;
    }
    exitAfterFatal("unhandledRejection", reason);
  });
}

installProcessSafetyNet();
