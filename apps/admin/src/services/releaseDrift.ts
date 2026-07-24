/** Public release signals for the admin drift matrix (client-side, read-only). */

const GITHUB_LATEST =
  "https://api.github.com/repos/Lawofall/AgentCore-releases/releases/latest";
const WEBSITE_RELEASE = "https://fashitianxia.xyz/api/desktop-release";

export interface ReleaseDriftSnapshot {
  desktopGithubTag: string | null;
  desktopGithubVersion: string | null;
  websiteDownloadVersion: string | null;
  errors: string[];
}

function stripTagPrefix(tag: string): string {
  return tag.replace(/^v/i, "");
}

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<T>;
}

export async function fetchReleaseDrift(): Promise<ReleaseDriftSnapshot> {
  const errors: string[] = [];
  let desktopGithubTag: string | null = null;
  let desktopGithubVersion: string | null = null;
  let websiteDownloadVersion: string | null = null;

  try {
    const gh = await fetchJson<{ tag_name?: string }>(GITHUB_LATEST);
    if (gh.tag_name) {
      desktopGithubTag = gh.tag_name;
      desktopGithubVersion = stripTagPrefix(gh.tag_name);
    }
  } catch (err) {
    errors.push(
      `GitHub Latest: ${err instanceof Error ? err.message : String(err)}`,
    );
  }

  try {
    const site = await fetchJson<{ version?: string }>(WEBSITE_RELEASE);
    websiteDownloadVersion = site.version ?? null;
  } catch (err) {
    errors.push(
      `下载页 API: ${err instanceof Error ? err.message : String(err)}`,
    );
  }

  return {
    desktopGithubTag,
    desktopGithubVersion,
    websiteDownloadVersion,
    errors,
  };
}

export function versionsMatch(a: string | null, b: string | null): boolean | null {
  if (!a || !b) return null;
  return a === b;
}
