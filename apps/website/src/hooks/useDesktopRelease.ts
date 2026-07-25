"use client";

import {
  ANDROID_APK_FILENAME,
  ANDROID_APK_URL,
  ANDROID_VERSION,
  DESKTOP_VERSION,
  MAC_DMG_FILENAME,
  MAC_DMG_URL,
  RELEASE_NOTES_URL,
  WIN_INSTALLER_FILENAME,
  WIN_INSTALLER_URL,
} from "@/lib/download";
import {
  DESKTOP_RELEASE_API,
  type ReleaseArtifacts,
} from "@/lib/release";
import { useEffect, useState } from "react";

function buildTimeFallback(): ReleaseArtifacts {
  return {
    version: DESKTOP_VERSION,
    releaseNotesUrl: RELEASE_NOTES_URL,
    winUrl: WIN_INSTALLER_URL,
    winFilename: WIN_INSTALLER_FILENAME,
    macUrl: MAC_DMG_URL,
    macFilename: MAC_DMG_FILENAME,
    androidUrl: ANDROID_APK_URL,
    androidFilename: ANDROID_APK_FILENAME,
    androidVersion: ANDROID_VERSION,
  };
}

/**
 * Runtime release metadata from Cloudflare Pages Function (falls back to
 * build-time download.generated.ts if the API is unreachable).
 */
export function useDesktopRelease() {
  const [artifacts, setArtifacts] = useState<ReleaseArtifacts>(buildTimeFallback);
  const [ready, setReady] = useState(false);

  useEffect(() => {
    let cancelled = false;
    void (async () => {
      try {
        const res = await fetch(DESKTOP_RELEASE_API);
        if (!res.ok) return;
        const data = (await res.json()) as ReleaseArtifacts;
        if (!cancelled && data?.version) {
          setArtifacts({
            ...buildTimeFallback(),
            ...data,
            androidUrl: data.androidUrl ?? "",
            androidFilename: data.androidFilename ?? "",
            androidVersion: data.androidVersion ?? "",
          });
        }
      } catch {
        // Keep build-time fallback.
      } finally {
        if (!cancelled) setReady(true);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return { artifacts, ready };
}
