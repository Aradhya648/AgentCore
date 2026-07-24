/**
 * 国内本地 Windows 安装包构建入口：在 `build:win` 前注入 npmmirror 镜像与
 * CSC_IDENTITY_AUTO_DISCOVERY=false（跳过 winCodeSign 下载，MVP 未签名）。
 *
 * `.npmrc` 已配 electron 镜像；此处显式设环境变量，确保 electron-builder
 * 二进制与 Electron zip 均走镜像，并避免打包阶段 10 分钟超时。
 * CI（GitHub Actions 直连）走 `build:win`，不用此脚本。
 */
import { spawnSync } from "node:child_process";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const root = join(dirname(fileURLToPath(import.meta.url)), "..");

const env = {
  ...process.env,
  ELECTRON_MIRROR: "https://npmmirror.com/mirrors/electron/",
  ELECTRON_BUILDER_BINARIES_MIRROR:
    "https://npmmirror.com/mirrors/electron-builder-binaries/",
  CSC_IDENTITY_AUTO_DISCOVERY: "false",
};

const result = spawnSync("pnpm", ["run", "build:win"], {
  cwd: root,
  stdio: "inherit",
  env,
  shell: true,
});

process.exit(result.status ?? 1);
