import { Capacitor } from "@capacitor/core";

declare const __APP_VERSION__: string;
declare const __APP_GIT_SHA__: string;

/** Header / About display only — do not branch product logic on this. */
export function clientPlatform(): "android" | "mobile-web" {
  return Capacitor.getPlatform() === "android" ? "android" : "mobile-web";
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
