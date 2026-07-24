import type { FilePreviewResult } from "@/lib/fileSource";
import { formatBytes } from "@/lib/format";
import { FileText } from "lucide-react";

/**
 * Shared body renderer for a {@link FilePreviewResult} — the source-agnostic
 * inner view used by both file UIs (文件中枢统一). Renders text (with an optional
 * truncation banner), an inline image, or a non-previewable fallback (binary /
 * too-large). Surrounding chrome (header, download / edit actions) belongs to the
 * caller; this draws content only.
 */
export function FilePreviewBody({
  result,
  name,
}: {
  result: FilePreviewResult;
  name: string;
}) {
  if (result.kind === "text") {
    return (
      <div className="flex h-full flex-col">
        {result.truncated && (
          <div className="shrink-0 border-b border-border bg-muted/40 px-4 py-1.5 text-xs text-muted-foreground">
            内容较大，仅显示前一部分，完整内容请下载查看。
          </div>
        )}
        <pre className="min-h-0 flex-1 overflow-auto whitespace-pre-wrap break-words px-4 py-3 font-mono text-xs leading-relaxed text-foreground">
          {result.text}
        </pre>
      </div>
    );
  }

  if (result.kind === "image") {
    return (
      <div className="flex h-full flex-col">
        <div className="flex min-h-0 flex-1 items-center justify-center overflow-auto p-4">
          <img
            src={result.dataUrl}
            alt={name}
            className="max-h-full max-w-full object-contain"
          />
        </div>
        <div className="shrink-0 border-t border-border px-4 py-1.5 text-xs text-muted-foreground">
          {result.mime} · {formatBytes(result.size)}
        </div>
      </div>
    );
  }

  // binary | too-large — not previewable inline.
  const meta =
    result.kind === "binary" && result.mime
      ? `${result.mime}${result.size != null ? ` · ${formatBytes(result.size)}` : ""}`
      : null;
  return (
    <div className="flex h-full flex-col items-center justify-center gap-2 px-4 text-center">
      <FileText size={26} className="text-muted-foreground/40" />
      <p className="text-sm text-muted-foreground">
        {result.kind === "too-large" ? "文件过大" : "无法预览此文件"}
      </p>
      <p className="text-xs text-muted-foreground/70">
        {result.kind === "too-large"
          ? "文件较大，不在面板内预览，请下载查看。"
          : (result.reason ?? "这是二进制文件，请下载后查看。")}
      </p>
      {meta && <p className="text-xs text-muted-foreground/60">{meta}</p>}
    </div>
  );
}
