/**
 * Latest desktop + Android download artifacts for the website.
 * User-facing installer URLs = GitHub Releases；版本发现可读品牌域 latest.json。
 *
 * Discovery order:
 *   1. CDN desktop/latest.json + android/latest.json（version / filenames）
 *   2. FALLBACK_VERSION → 构造 GitHub asset URLs（SSG / offline）
 *
 * → apps/website/functions/_lib/downloadsCdn.mjs · 发布与门禁.md §7.6b
 */
import {
  androidArtifactUrls,
  androidLatestJsonUrl,
  artifactUrlsForVersion,
  desktopLatestJsonUrl,
} from "./downloadsCdn.mjs";

/** @typedef {{
 *   version: string,
 *   releaseNotesUrl: string,
 *   winUrl: string,
 *   winFilename: string,
 *   macUrl: string,
 *   macFilename: string,
 *   androidUrl: string,
 *   androidFilename: string,
 *   androidVersion: string,
 * }} ReleaseArtifacts */

const EMPTY_ANDROID = {
  androidUrl: "",
  androidFilename: "",
  androidVersion: "",
};

export { artifactUrlsForVersion };

/**
 * @returns {Promise<{ androidUrl: string, androidFilename: string, androidVersion: string }>}
 */
async function fetchLatestAndroidArtifacts() {
  try {
    const res = await fetch(androidLatestJsonUrl(), {
      headers: { "User-Agent": "agentcore-website" },
    });
    if (!res.ok) return { ...EMPTY_ANDROID };
    const data = await res.json();
    const version = String(data.version ?? "").trim();
    const filename = String(data.filename ?? "").trim();
    if (!version || !filename) return { ...EMPTY_ANDROID };
    // Always reconstruct GitHub URL — ignore stale brand-host downloadUrl in manifest.
    return androidArtifactUrls(version, filename);
  } catch {
    return { ...EMPTY_ANDROID };
  }
}

/**
 * Latest published desktop artifacts from CDN manifest, merged with Android.
 *
 * When CDN manifest is older than ``fallbackVersion`` (bump already in source
 * but CDN not synced yet), keep the fallback so a premature website deploy
 * cannot bake a regressive version into SSG.
 *
 * @param {string} fallbackVersion
 * @returns {Promise<ReleaseArtifacts>}
 */
export async function fetchLatestReleaseArtifacts(fallbackVersion) {
  const fallback = {
    ...artifactUrlsForVersion(fallbackVersion),
    ...EMPTY_ANDROID,
  };
  const android = await fetchLatestAndroidArtifacts();

  try {
    const res = await fetch(desktopLatestJsonUrl(), {
      headers: { "User-Agent": "agentcore-website" },
    });
    if (!res.ok) {
      throw new Error(`CDN desktop latest.json HTTP ${res.status}`);
    }
    const data = await res.json();
    const version = String(data.version ?? "").trim();
    if (!version) throw new Error("CDN desktop latest.json missing version");

    if (compareSemver(fallbackVersion, version) > 0) {
      return { ...fallback, ...android };
    }

    const winFilename = String(data.winFilename ?? "").trim();
    const macFilename = String(data.macFilename ?? "").trim();
    if (!winFilename) throw new Error("CDN desktop latest.json missing winFilename");

    const base = artifactUrlsForVersion(version, { macFilename });
    return {
      version,
      releaseNotesUrl:
        String(data.releaseNotesUrl ?? "").trim() || base.releaseNotesUrl,
      // Always GitHub — ignore stale brand-host winUrl/macUrl in manifest.
      winUrl: base.winUrl,
      winFilename,
      macUrl: macFilename ? base.macUrl : "",
      macFilename,
      ...android,
    };
  } catch {
    return { ...fallback, ...android };
  }
}

/** @param {string} a @param {string} b @returns {number} */
function compareSemver(a, b) {
  const pa = String(a).split(".").map((x) => parseInt(x, 10) || 0);
  const pb = String(b).split(".").map((x) => parseInt(x, 10) || 0);
  const n = Math.max(pa.length, pb.length);
  for (let i = 0; i < n; i++) {
    const d = (pa[i] ?? 0) - (pb[i] ?? 0);
    if (d !== 0) return d;
  }
  return 0;
}
