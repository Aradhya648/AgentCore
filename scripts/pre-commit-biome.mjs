#!/usr/bin/env node
/**
 * pre-commit local hook: biome check only on staged desktop/mobile src files.
 * Avoids full-tree lint and keeps Prettier out of the loop (Biome is the format gate).
 */
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

/** @type {Record<"desktop" | "mobile", string[]>} */
const byApp = { desktop: [], mobile: [] };

for (const raw of process.argv.slice(2)) {
  const norm = raw.replace(/\\/g, "/");
  if (norm.startsWith("apps/desktop/")) {
    byApp.desktop.push(norm.slice("apps/desktop/".length));
  } else if (norm.startsWith("apps/mobile/")) {
    byApp.mobile.push(norm.slice("apps/mobile/".length));
  }
}

/**
 * @param {"desktop" | "mobile"} app
 * @param {string[]} relFiles
 * @returns {number}
 */
function runBiome(app, relFiles) {
  const srcFiles = relFiles.filter((f) => f.startsWith("src/"));
  if (srcFiles.length === 0) return 0;

  const result = spawnSync(
    "pnpm",
    ["exec", "biome", "check", ...srcFiles],
    {
      cwd: path.join(repoRoot, "apps", app),
      stdio: "inherit",
      shell: true,
      env: process.env,
    },
  );
  if (result.error) {
    console.error(`[pre-commit-biome] failed to spawn biome for apps/${app}:`, result.error.message);
    return 1;
  }
  return result.status ?? 1;
}

let exitCode = 0;
for (const app of /** @type {const} */ (["desktop", "mobile"])) {
  const code = runBiome(app, byApp[app]);
  if (code !== 0) exitCode = code;
}
process.exit(exitCode);
