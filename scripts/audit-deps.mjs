#!/usr/bin/env node
/**
 * Soft dependency audit (P3-3): run Python + JS scanners sequentially.
 * Non-zero exit = findings present; CI nightly uses continue-on-error.
 * Does not clear CVEs; reports only.
 */
import { spawnSync } from "node:child_process";

function run(script) {
  const r = spawnSync("pnpm", ["run", script], {
    stdio: "inherit",
    shell: true,
    env: process.env,
  });
  return r.status ?? 1;
}

const py = run("audit:deps:py");
const js = run("audit:deps:js");
process.exit(py !== 0 || js !== 0 ? 1 : 0);
