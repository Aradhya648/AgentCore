/**
 * Read client semver + git SHA for Vite build injection.
 * Used by desktop / mobile / admin vite configs.
 */
import { execSync } from "node:child_process";
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";

export function readClientBuildInfo(packageJsonUrl) {
  const pkg = JSON.parse(readFileSync(fileURLToPath(packageJsonUrl), "utf8"));
  let gitSha = "unknown";
  try {
    gitSha = execSync("git rev-parse --short HEAD", {
      encoding: "utf8",
      timeout: 2000,
    }).trim();
  } catch {
    /* not a git checkout or git unavailable */
  }
  return { version: pkg.version ?? "0.0.0", gitSha };
}

export function viteClientBuildDefine(packageJsonUrl) {
  const info = readClientBuildInfo(packageJsonUrl);
  return {
    __APP_VERSION__: JSON.stringify(info.version),
    __APP_GIT_SHA__: JSON.stringify(info.gitSha),
  };
}
