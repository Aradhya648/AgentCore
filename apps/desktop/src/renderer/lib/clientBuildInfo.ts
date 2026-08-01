import { isWebRuntime } from "@/lib/capabilities";

declare const __APP_VERSION__: string;
declare const __APP_GIT_SHA__: string;

/** Electron 外壳为 desktop；浏览器 web 运行时（`isWebRuntime` / `__WEB__`）为 web。 */
export function clientPlatform(): "desktop" | "web" {
  return isWebRuntime() ? "web" : "desktop";
}

export function clientVersion(): string {
  return typeof __APP_VERSION__ !== "undefined" ? __APP_VERSION__ : "dev";
}

export function clientGitSha(): string {
  return typeof __APP_GIT_SHA__ !== "undefined" ? __APP_GIT_SHA__ : "unknown";
}

export function clientHeaders(): Record<string, string> {
  return {
    "X-Client-Platform": clientPlatform(),
    "X-Client-Version": clientVersion(),
  };
}

export function formatGitSha(sha: string): string {
  return sha === "unknown" ? "未标记（本地开发）" : sha;
}
