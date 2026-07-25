/**
 * Brand download CDN contract (self-hosted nginx on production + Tunnel hostname).
 *
 * User-facing installers / APK / electron-updater feeds live here.
 * GitHub AgentCore-releases remains the upload source + history archive.
 *
 * Layout:
 *   {BASE}/desktop/latest.yml|latest-mac.yml|latest.json|AgentCore-*
 *   {BASE}/android/latest.json|AgentCore-*-android.apk
 *
 * → docs/05-平台与运维/部署与运维.md §7.6b
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
 * Absolute CDN URL for a key under the downloads host.
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
 * Build website / API artifact URLs for a known desktop version.
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
    winUrl: cdnUrl(`${DOWNLOADS_DESKTOP_PREFIX}/${winFilename}`),
    winFilename,
    macUrl: macFilename
      ? cdnUrl(`${DOWNLOADS_DESKTOP_PREFIX}/${macFilename}`)
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
    androidUrl: cdnUrl(`${DOWNLOADS_ANDROID_PREFIX}/${apkName}`),
  };
}

/**
 * Desktop feed manifest written to R2 on sync (website + admin drift).
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
    winUrl: cdnUrl(`${DOWNLOADS_DESKTOP_PREFIX}/${input.winFilename}`),
    macUrl: macFilename
      ? cdnUrl(`${DOWNLOADS_DESKTOP_PREFIX}/${macFilename}`)
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
