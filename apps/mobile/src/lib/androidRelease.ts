/**
 * Latest published Android APK from brand CDN
 * (downloads host /android/latest.json). Fail-open on network errors.
 * GitHub AgentCore-releases is archive-only for end users.
 */

const ANDROID_LATEST_JSON =
  "https://downloads.fashitianxia.xyz/android/latest.json";

export type AndroidApkRelease = {
  version: string;
  downloadUrl: string;
  filename: string;
};

/**
 * Newest Android APK advertised on the download CDN.
 * Fail-open: network / parse errors -> null (no banner).
 */
export async function fetchLatestAndroidApk(): Promise<AndroidApkRelease | null> {
  try {
    const res = await fetch(ANDROID_LATEST_JSON, {
      headers: { Accept: "application/json" },
    });
    if (!res.ok) return null;
    const data: unknown = await res.json();
    if (!data || typeof data !== "object") return null;
    const obj = data as {
      version?: string;
      filename?: string;
      downloadUrl?: string;
    };
    const version = String(obj.version ?? "").trim();
    const filename = String(obj.filename ?? "").trim();
    const downloadUrl = String(obj.downloadUrl ?? "").trim();
    if (!version || !filename || !downloadUrl) return null;
    return { version, filename, downloadUrl };
  } catch {
    return null;
  }
}

/** Open the APK download URL in the system browser (sideload, not in-app install). */
export function openApkDownload(url: string): void {
  window.open(url, "_blank", "noopener,noreferrer");
}
