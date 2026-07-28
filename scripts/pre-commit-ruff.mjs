#!/usr/bin/env node
/**
 * pre-commit local hook: ruff check on staged apps/server Python files.
 * Uses the repo's uv + apps/server pyproject (no separate pre-commit ruff env).
 */
import { spawnSync } from "node:child_process";
import path from "node:path";
import { fileURLToPath } from "node:url";

const repoRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const files = process.argv
  .slice(2)
  .map((f) => f.replace(/\\/g, "/"))
  .filter((f) => f.startsWith("apps/server/") && /\.pyi?$/.test(f));

if (files.length === 0) process.exit(0);

const result = spawnSync(
  "uv",
  ["run", "ruff", "check", "--config", "apps/server/pyproject.toml", ...files],
  {
    cwd: repoRoot,
    stdio: "inherit",
    shell: true,
    env: process.env,
  },
);

if (result.error) {
  console.error("[pre-commit-ruff] failed to spawn uv/ruff:", result.error.message);
  process.exit(1);
}
process.exit(result.status ?? 1);
