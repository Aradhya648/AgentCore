/**
 * Launcher — real script lives next to other Playwright harnesses:
 *   node apps/desktop/scripts/promo_capture_lv_molihua.mjs
 */
import { spawn } from "node:child_process";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const target = resolve(here, "../apps/desktop/scripts/promo_capture_lv_molihua.mjs");
const child = spawn(process.execPath, [target, ...process.argv.slice(2)], {
  stdio: "inherit",
  env: process.env,
  cwd: resolve(here, "../apps/desktop"),
});
child.on("exit", (code) => process.exit(code ?? 1));
