/**
 * Soft outdated-Android banner (sideload). Shown when the installed APK is older
 * than brand CDN `android/latest.json`. Dismissible for the session; CTA opens
 * the CDN APK URL in the system browser.
 */
import {
  dismissAndroidUpdate,
  openAndroidDownload,
  useAndroidUpdates,
} from "@/lib/androidUpdates";

export function OutdatedAndroidBanner() {
  const { availableVersion, dismissed, downloadUrl } = useAndroidUpdates();

  if (!availableVersion || dismissed || !downloadUrl) return null;

  return (
    // biome-ignore lint/a11y/useSemanticElements: 内嵌 CTA / 关闭按钮，<output> 语义不符——保留 aria live 容器。
    <div className="outdated-android-banner" role="status">
      <span className="outdated-android-banner-text">
        有新版本 {availableVersion} 可下载
      </span>
      <button
        type="button"
        className="outdated-android-banner-cta"
        onClick={() => openAndroidDownload()}
      >
        去下载
      </button>
      <button
        type="button"
        className="outdated-android-banner-dismiss"
        aria-label="关闭"
        onClick={() => dismissAndroidUpdate()}
      >
        ×
      </button>
    </div>
  );
}
