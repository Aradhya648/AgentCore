/**
 * 桌面端下载配置（构建时由 scripts/fetch-release.mjs 从 GitHub Releases 刷新）。
 */
import {
  DESKTOP_VERSION,
  MAC_DMG_FILENAME,
  MAC_DMG_URL,
  RELEASE_NOTES_URL,
  WIN_INSTALLER_FILENAME,
  WIN_INSTALLER_URL,
} from "./download.generated";

export {
  DESKTOP_VERSION,
  MAC_DMG_FILENAME,
  MAC_DMG_URL,
  RELEASE_NOTES_URL,
  WIN_INSTALLER_FILENAME,
  WIN_INSTALLER_URL,
};

export const RELEASES_REPO =
  "https://github.com/Lawofall/AgentCore-releases" as const;

export const RELEASES_LATEST = `${RELEASES_REPO}/releases/latest` as const;

export type PlatformId = "win" | "mac" | "linux";

export type PlatformDownload = {
  id: PlatformId;
  label: string;
  subtitle: string;
  available: boolean;
  url?: string;
  fileLabel?: string;
};

const macAvailable = Boolean(MAC_DMG_URL);

/** Build platform rows from release artifact URLs (runtime or build-time). */
export function platformsFromArtifacts(artifacts: {
  winUrl: string;
  winFilename: string;
  macUrl: string;
  macFilename: string;
}): PlatformDownload[] {
  const macReady = Boolean(artifacts.macUrl);
  return [
    {
      id: "win",
      label: "Windows",
      subtitle: "Windows 10/11 · 64 位",
      available: true,
      url: artifacts.winUrl,
      fileLabel: artifacts.winFilename,
    },
    {
      id: "mac",
      label: "macOS",
      subtitle: "Apple Silicon（M 系列 / arm64）",
      available: macReady,
      url: macReady ? artifacts.macUrl : undefined,
      fileLabel: macReady ? artifacts.macFilename : undefined,
    },
    {
      id: "linux",
      label: "Linux",
      subtitle: "AppImage",
      available: false,
    },
  ];
}

export const PLATFORMS: PlatformDownload[] = platformsFromArtifacts({
  winUrl: WIN_INSTALLER_URL,
  winFilename: WIN_INSTALLER_FILENAME,
  macUrl: MAC_DMG_URL,
  macFilename: MAC_DMG_FILENAME,
});

export const SYSTEM_REQUIREMENTS: Record<PlatformId, string[]> = {
  win: [
    "Windows 10 或 11（64 位）",
    "8 GB 内存（推荐 16 GB）",
    "约 500 MB 可用磁盘空间",
    "可访问 agentcore 云端 API（需联网）",
  ],
  mac: [
    "Apple Silicon Mac（M 系列 / arm64）",
    "Intel Mac 不在支持范围",
    "macOS 13 Ventura 或更高版本",
    "8 GB 内存（推荐 16 GB）",
    "内测包未签名：首次打开须右键 → 打开",
  ],
  linux: ["即将推出"],
};

export const WIN_INSTALL_STEPS = [
  "下载并运行安装程序，按向导完成安装。",
  "首次启动注册账号并登录。",
  "在设置 → 关于 可检查更新；已安装用户会自动收到新版本。",
];

export const MAC_INSTALL_STEPS = [
  "下载 DMG，将 AgentCore 拖入「应用程序」文件夹。",
  "首次打开：在启动台或应用程序文件夹中右键 AgentCore →「打开」→ 确认（内测包未签名，勿直接双击）。",
  "注册账号并登录；设置 → 关于 可检查更新（更新安装后可能需再次右键打开）。",
];

export const DOWNLOAD_PAGE_PATH = "/download" as const;

/** 手机端 web SPA（Cloudflare Pages · deploy-mobile-web.yml） */
export const MOBILE_WEB_URL = "https://m.fashitianxia.xyz" as const;

/** 主力 web 客户端（apps/desktop 渲染层跑浏览器，同源托管在 app. 根路径；免安装、需登录）。 */
export const WEB_APP_URL = "https://app.fashitianxia.xyz" as const;
