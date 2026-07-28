/**
 * Brand download CDN + GitHub Releases URL helpers.
 *
 * - 官网首装 / 用户面安装包按钮 → GitHub Releases（`releases/download/...`）
 * - electron-updater feed + latest.json 宿主 → 品牌域 downloads.*（自有机 nginx；你试国内 OSS 时可换）
 * - GitHub AgentCore-releases 同时是上传源与历史归档
 *
 * Layout on brand host:
 *   {BASE}/desktop/latest.yml|latest-mac.yml|latest.json|AgentCore-*
 *   {BASE}/android/latest.json|AgentCore-*-android.apk
 *
 * → docs/05-平台与运维/发布与门禁.md §7.6b
 */

/** Resolve base URL — Node (sync/fetch-release) may override via env; Pages Functions have no `process`. */
function resolveDownloadsBase() {
  try {
    const fromEnv =
      typeof process !== "undefined" &&
      process.env &&
      typeof process.env.AGENTCORE_DOWNLOADS_BASE === "string"
        ? process.env.AGENTCORE_DOWNLOADS_BASE.trim()
        : "";
    if (fromEnv) return fromEnv;
  } catch {
    // ignore
  }
  return "https://downloads.fashitianxia.xyz";
}

export const DOWNLOADS_BASE = resolveDownloadsBase();

export const DOWNLOADS_DESKTOP_PREFIX = "desktop";
export const DOWNLOADS_ANDROID_PREFIX = "android";

export const RELEASES_REPO = "Lawofall/AgentCore-releases";
export const RELEASES_REPO_URL = `https://github.com/${RELEASES_REPO}`;

/** @param {string} version */
export function winInstallerFilename(version) {
  return `AgentCore-${version}-win-x64.exe`;
}

/** @param {string} version */
export function macDmgFilename(version) {
  return `AgentCore-${version}-mac-arm64.dmg`;
}

/** @param {string} version */
export function androidApkFilename(version) {
  return `AgentCore-${version}-android.apk`;
}

/** @param {string} version */
export function githubReleaseNotesUrl(version) {
  return `${RELEASES_REPO_URL}/releases/tag/v${version}`;
}

/** @param {string} version */
export function githubAndroidReleaseNotesUrl(version) {
  return `${RELEASES_REPO_URL}/releases/tag/android-v${version}`;
}

/**
 * User-facing desktop installer URL (GitHub Releases asset).
 * @param {string} version
 * @param {string} filename
 */
export function githubDesktopAssetUrl(version, filename) {
  return `${RELEASES_REPO_URL}/releases/download/v${version}/${filename}`;
}

/**
 * User-facing Android APK URL (GitHub Releases asset).
 * @param {string} version
 * @param {string} filename
 */
export function githubAndroidAssetUrl(version, filename) {
  return `${RELEASES_REPO_URL}/releases/download/android-v${version}/${filename}`;
}

/**
 * Absolute brand-host URL for a key (updater feed / manifests — not官网首装主链).
 * @param {string} key e.g. "desktop/latest.yml"
 */
export function cdnUrl(key) {
  const base = DOWNLOADS_BASE.replace(/\/$/, "");
  const path = String(key).replace(/^\//, "");
  return `${base}/${path}`;
}

/** electron-updater generic feed (latest.yml + installers share this directory). */
export function desktopFeedUrl() {
  return cdnUrl(DOWNLOADS_DESKTOP_PREFIX);
}

export function desktopLatestJsonUrl() {
  return cdnUrl(`${DOWNLOADS_DESKTOP_PREFIX}/latest.json`);
}

export function androidLatestJsonUrl() {
  return cdnUrl(`${DOWNLOADS_ANDROID_PREFIX}/latest.json`);
}

/**
 * Build website artifact URLs for a known desktop version (GitHub Releases).
 * macFilename may be "" when that asset is not published yet.
 *
 * @param {string} version
 * @param {{ macFilename?: string }} [opts]
 */
export function artifactUrlsForVersion(version, opts = {}) {
  const winFilename = winInstallerFilename(version);
  const macFilename =
    opts.macFilename === undefined
      ? macDmgFilename(version)
      : opts.macFilename;
  return {
    version,
    releaseNotesUrl: githubReleaseNotesUrl(version),
    winUrl: githubDesktopAssetUrl(version, winFilename),
    winFilename,
    macUrl: macFilename
      ? githubDesktopAssetUrl(version, macFilename)
      : "",
    macFilename: macFilename || "",
  };
}

/**
 * @param {string} version
 * @param {string} [filename]
 */
export function androidArtifactUrls(version, filename) {
  const apkName = filename || androidApkFilename(version);
  return {
    androidVersion: version,
    androidFilename: apkName,
    androidUrl: githubAndroidAssetUrl(version, apkName),
  };
}

/**
 * Desktop feed manifest written on sync (website discovers version here;
 * winUrl/macUrl are GitHub so官网不依赖品牌域带宽).
 * @param {{
 *   version: string,
 *   winFilename: string,
 *   macFilename?: string,
 *   releaseNotesUrl?: string,
 * }} input
 */
export function buildDesktopLatestJson(input) {
  const macFilename = input.macFilename || "";
  return {
    version: input.version,
    releaseNotesUrl:
      input.releaseNotesUrl || githubReleaseNotesUrl(input.version),
    winFilename: input.winFilename,
    macFilename,
    winUrl: githubDesktopAssetUrl(input.version, input.winFilename),
    macUrl: macFilename
      ? githubDesktopAssetUrl(input.version, macFilename)
      : "",
    updatedAt: new Date().toISOString(),
  };
}

/**
 * @param {{ version: string, filename?: string }} input
 */
export function buildAndroidLatestJson(input) {
  const filename = input.filename || androidApkFilename(input.version);
  const urls = androidArtifactUrls(input.version, filename);
  return {
    version: input.version,
    filename,
    downloadUrl: urls.androidUrl,
    releaseNotesUrl: githubAndroidReleaseNotesUrl(input.version),
    updatedAt: new Date().toISOString(),
  };
}
