/**
 * Electron 42+ no longer runs install.js on postinstall. We invoke it explicitly
 * after `pnpm gen:api`. If the default GitHub download fails (common in CN),
 * retry via npmmirror.
 */
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const pathTxt = join(root, "node_modules/electron/path.txt");
const installJs = join(root, "node_modules/electron/install.js");

if (existsSync(pathTxt)) {
  process.exit(0);
}

if (!existsSync(installJs)) {
  console.warn("[install-electron] electron package not found, skipping");
  process.exit(0);
}

function run(env = process.env) {
  return spawnSync(process.execPath, [installJs], {
    cwd: root,
    stdio: "inherit",
    env,
  });
}

let result = run();
if (result.status === 0 && existsSync(pathTxt)) {
  process.exit(0);
}

console.warn(
  "[install-electron] default download failed, retrying via npmmirror…",
);
result = run({
  ...process.env,
  ELECTRON_MIRROR: "https://npmmirror.com/mirrors/electron/",
});
process.exit(result.status ?? 1);
