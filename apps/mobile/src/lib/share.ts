// Native share / save for the mobile client (前端技术与架构 §七 · 文件增强).
//
// Best-effort: on a device that supports the Web Share API with files (iOS Safari,
// Android Chrome, the Capacitor webview), this hands the bytes to the OS share sheet
// (AirDrop / 存储到文件 / 发送给 App). Everywhere else it degrades to an object-URL
// download. We intentionally avoid a native filesystem plugin (the "minimal deps"
// decision) — the Web Share sheet already covers 保存到文件 on both platforms.

/** Trigger a plain browser download from a blob (the universal fallback). */
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

/** True when the OS share sheet can take a file (so the UI can label the action 分享). */
export function canShareFiles(): boolean {
  if (typeof navigator === "undefined" || !navigator.canShare) return false;
  try {
    return navigator.canShare({ files: [new File([new Blob()], "probe")] });
  } catch {
    return false;
  }
}

/**
 * Share a file through the OS sheet, falling back to a download. Returns how it was
 * handled so the caller can word a toast ("已分享" vs "已下载"). A user-cancelled share
 * counts as handled (no fallback download — they dismissed it on purpose).
 */
export async function shareOrDownloadFile(
  blob: Blob,
  filename: string,
  type?: string,
): Promise<"shared" | "downloaded"> {
  const file = new File([blob], filename, {
    type: type || blob.type || "application/octet-stream",
  });
  if (navigator.canShare?.({ files: [file] })) {
    try {
      await navigator.share({ files: [file], title: filename });
      return "shared";
    } catch (e) {
      // User dismissed the sheet → done, don't also download.
      if (e instanceof DOMException && e.name === "AbortError") return "shared";
      // Any other failure → fall through to the download fallback.
    }
  }
  downloadBlob(blob, filename);
  return "downloaded";
}
