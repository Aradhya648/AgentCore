/**
 * node-pty 原生模块：优先官方 prebuilds（N-API，Electron 可直接加载）。
 * 可选 `@electron/rebuild` 回落——缺 Spectre 缓解库等工具链时跳过，不阻断 install。
 */
import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");
const require = createRequire(import.meta.url);

function hasPrebuild() {
  try {
    const ptyRoot = dirname(require.resolve("node-pty/package.json"));
    const plat = `${process.platform}-${process.arch}`;
    return existsSync(join(ptyRoot, "prebuilds", plat, "pty.node"));
  } catch {
    return false;
  }
}

if (hasPrebuild()) {
  console.log(
    "[rebuild-native] node-pty prebuild present — skip electron-rebuild",
  );
  process.exit(0);
}

console.log("[rebuild-native] no prebuild; trying electron-rebuild…");
const result = spawnSync(
  process.platform === "win32" ? "pnpm.cmd" : "pnpm",
  ["exec", "electron-rebuild", "-f", "-w", "node-pty"],
  { cwd: root, stdio: "inherit", shell: true },
);

if (result.status !== 0) {
  console.warn(
    "[rebuild-native] electron-rebuild failed — node-pty may be unavailable until a prebuild or toolchain is available",
  );
  // 不阻断 install：开发机可能缺 MSVC Spectre 库；CI/发版机应有 prebuild 或完整工具链。
  process.exit(0);
}
process.exit(0);
