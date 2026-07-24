/** @typedef {{ version: string, releaseNotesUrl: string, winUrl: string, winFilename: string, macUrl: string, macFilename: string }} ReleaseArtifacts */

const RELEASES_REPO = "Lawofall/AgentCore-releases";

/** @param {string} version */
export function artifactUrlsForVersion(version) {
  const base = `https://github.com/${RELEASES_REPO}/releases/download/v${version}`;
  return {
    version,
    releaseNotesUrl: `https://github.com/${RELEASES_REPO}/releases/tag/v${version}`,
    winUrl: `${base}/AgentCore-${version}-win-x64.exe`,
    winFilename: `AgentCore-${version}-win-x64.exe`,
    macUrl: `${base}/AgentCore-${version}-mac-arm64.dmg`,
    macFilename: `AgentCore-${version}-mac-arm64.dmg`,
  };
}

/**
 * Latest **published** (non-draft) release artifacts for the download page.
 * Skips draft latest (CI upload) so the site stays on the last public version
 * until Publish — same rule as build-time fetch-release.mjs.
 *
 * When GitHub latest is **older** than ``fallbackVersion`` (bump already landed
 * in source but the release is not published yet), keep the fallback so a
 * premature website deploy cannot bake a regressive version into SSG.
 *
 * @param {string} fallbackVersion
 * @returns {Promise<ReleaseArtifacts>}
 */
export async function fetchLatestReleaseArtifacts(fallbackVersion) {
  const fallback = artifactUrlsForVersion(fallbackVersion);
  try {
    const res = await fetch(
      `https://api.github.com/repos/${RELEASES_REPO}/releases/latest`,
      { headers: { "User-Agent": "agentcore-website" } },
    );
    if (!res.ok) {
      throw new Error(`GitHub API ${res.status}`);
    }
    const data = await res.json();
    if (data.draft) {
      throw new Error(`Latest release ${data.tag_name} is still draft`);
    }
    const version = String(data.tag_name).replace(/^v/, "");
    if (compareSemver(fallbackVersion, version) > 0) {
      // Source FALLBACK is ahead of GitHub latest — prefer FALLBACK URLs.
      return fallback;
    }
    const assets = data.assets ?? [];
    const winAsset = assets.find((a) => /-win-x64\.exe$/i.test(a.name));
    const macAsset = assets.find((a) => /-mac-arm64\.dmg$/i.test(a.name));
    const base = artifactUrlsForVersion(version);
    return {
      version,
      releaseNotesUrl: data.html_url ?? base.releaseNotesUrl,
      winUrl: winAsset?.browser_download_url ?? base.winUrl,
      winFilename: winAsset?.name ?? base.winFilename,
      macUrl: macAsset?.browser_download_url ?? "",
      macFilename: macAsset?.name ?? "",
    };
  } catch {
    return fallback;
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
