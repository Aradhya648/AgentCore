import { loadEnv } from "electron-vite";

const FALLBACK_API_BASE = "http://localhost:8000";

/**
 * 主进程 `__API_BASE_URL__`（CSP connect-src / img-src）与渲染层 `VITE_API_URL` 同源。
 *
 * 生产构建必须读包根 `.env.production`，不能被：
 * 1. `process.cwd()` 指到 monorepo 根（读不到 `.env.production` → 回落 `.env` localhost）
 * 2. 壳里残留的 `process.env.VITE_API_URL=localhost`（Vite loadEnv 会盖过文件值）
 * 盖掉。
 */
export function resolveApiBaseUrl(
  mode: string,
  command: string,
  envDir: string,
): string {
  if (command === "build" || mode === "production") {
    const saved = process.env.VITE_API_URL;
    delete process.env.VITE_API_URL;
    try {
      return loadEnv("production", envDir).VITE_API_URL || FALLBACK_API_BASE;
    } finally {
      if (saved !== undefined) process.env.VITE_API_URL = saved;
      else delete process.env.VITE_API_URL;
    }
  }
  return loadEnv(mode, envDir).VITE_API_URL || FALLBACK_API_BASE;
}
