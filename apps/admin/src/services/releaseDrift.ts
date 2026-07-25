/** Public release signals for the admin drift matrix (client-side, read-only). */

const CDN_DESKTOP_LATEST =
  "https://downloads.fashitianxia.xyz/desktop/latest.json";
const WEBSITE_RELEASE = "https://fashitianxia.xyz/api/desktop-release";

export interface ReleaseDriftSnapshot {
  /** Brand CDN desktop/latest.json version (user-facing installers + updater). */
  desktopCdnVersion: string | null;
  websiteDownloadVersion: string | null;
  errors: string[];
}

async function fetchJson<T>(url: string): Promise<T> {
  const res = await fetch(url, { headers: { Accept: "application/json" } });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  return res.json() as Promise<T>;
}

export async function fetchReleaseDrift(): Promise<ReleaseDriftSnapshot> {
  const errors: string[] = [];
  let desktopCdnVersion: string | null = null;
  let websiteDownloadVersion: string | null = null;

  try {
    const cdn = await fetchJson<{ version?: string }>(CDN_DESKTOP_LATEST);
    desktopCdnVersion = String(cdn.version ?? "").trim() || null;
  } catch (err) {
    errors.push(
      `下载 CDN: ${err instanceof Error ? err.message : String(err)}`,
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
    desktopCdnVersion,
    websiteDownloadVersion,
    errors,
  };
}

export function versionsMatch(a: string | null, b: string | null): boolean | null {
  if (!a || !b) return null;
  return a === b;
}
