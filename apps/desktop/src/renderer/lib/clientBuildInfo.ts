declare const __APP_VERSION__: string;
declare const __APP_GIT_SHA__: string;

export const CLIENT_PLATFORM = "desktop" as const;

export function clientVersion(): string {
  return typeof __APP_VERSION__ !== "undefined" ? __APP_VERSION__ : "dev";
}

export function clientGitSha(): string {
  return typeof __APP_GIT_SHA__ !== "undefined" ? __APP_GIT_SHA__ : "unknown";
}

export function clientHeaders(): Record<string, string> {
  return {
    "X-Client-Platform": CLIENT_PLATFORM,
    "X-Client-Version": clientVersion(),
  };
}

export function formatGitSha(sha: string): string {
  return sha === "unknown" ? "未标记（本地开发）" : sha;
}
