import { IconButton } from "@/components/ui";
import { notifyActionError } from "@/lib/toast";
import {
  type StoredAttachment,
  downloadChatAttachment,
  fetchChatAttachmentBlob,
} from "@/services/messaging";
import { ChevronLeft, ChevronRight, Download, ImageOff, X } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { createPortal } from "react-dom";

type ImageStatus = "loading" | "ready" | "failed";

/**
 * Cookie-authed fetch → object URL for an IM attachment path. Fetch rejection and
 * `<img onError>` both land on `failed` — no separate recovery path.
 *
 * When `fallbackPath` is set (bubble preview: thumb → original), a failed primary
 * fetch retries the fallback once before surfacing ImageOff.
 */
function useChatImageBlob(
  chatId: string,
  path: string | null | undefined,
  fallbackPath?: string | null,
): { url: string | null; status: ImageStatus; markFailed: () => void } {
  const [url, setUrl] = useState<string | null>(null);
  const [status, setStatus] = useState<ImageStatus>("loading");

  useEffect(() => {
    if (!path) {
      setUrl(null);
      setStatus("failed");
      return;
    }
    let active = true;
    let objectUrl: string | null = null;
    setUrl(null);
    setStatus("loading");

    const load = (candidate: string, allowFallback: boolean) =>
      fetchChatAttachmentBlob(chatId, candidate)
        .then((blob) => {
          if (!active) return;
          objectUrl = URL.createObjectURL(blob);
          setUrl(objectUrl);
          setStatus("ready");
        })
        .catch(() => {
          if (!active) return;
          const next =
            allowFallback && fallbackPath && fallbackPath !== candidate
              ? fallbackPath
              : null;
          if (next) {
            void load(next, false);
            return;
          }
          setUrl(null);
          setStatus("failed");
        });

    void load(path, true);
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [chatId, path, fallbackPath]);

  const markFailed = useCallback(() => {
    setStatus("failed");
  }, []);

  return { url, status, markFailed };
}

function FailedTile({ className }: { className?: string }) {
  return (
    <div
      className={`flex items-center justify-center bg-muted text-muted-foreground ${className ?? ""}`}
      role="img"
      aria-label="图片加载失败"
    >
      <ImageOff size={18} />
    </div>
  );
}

function LoadingTile({ className }: { className?: string }) {
  return (
    <div className={`animate-pulse bg-muted ${className ?? ""}`} aria-hidden />
  );
}

/** Bubble thumbnail: prefer `thumb_path`, fall back to `workspace_path` on fetch miss. */
function ChatImageThumb({
  chatId,
  attachment,
  count,
  onOpen,
}: {
  chatId: string;
  attachment: StoredAttachment;
  count: number;
  onOpen: () => void;
}) {
  const previewPath = attachment.thumb_path ?? attachment.workspace_path;
  const fallbackPath =
    attachment.thumb_path && attachment.workspace_path
      ? attachment.workspace_path
      : null;
  const { url, status, markFailed } = useChatImageBlob(
    chatId,
    previewPath,
    fallbackPath,
  );

  const tileClass =
    count === 1
      ? "max-h-60 max-w-[260px] rounded-lg"
      : count === 2
        ? "aspect-square w-full rounded-lg"
        : "aspect-square w-full rounded-lg";

  if (status === "failed") {
    return (
      <FailedTile
        className={`${tileClass} ${count === 1 ? "size-24" : "min-h-0"}`}
      />
    );
  }
  if (status === "loading" || !url) {
    return (
      <LoadingTile
        className={`${tileClass} ${count === 1 ? "size-24" : "min-h-0"}`}
      />
    );
  }

  return (
    <button
      type="button"
      onClick={onOpen}
      className={`block cursor-zoom-in overflow-hidden border border-border p-0 hover:opacity-95 focus:outline-none focus:ring-2 focus:ring-ring ${tileClass}`}
      title={attachment.name}
      aria-label={`查看 ${attachment.name}`}
    >
      <img
        src={url}
        alt={attachment.name}
        className={
          count === 1
            ? "max-h-60 max-w-[260px] object-cover"
            : "h-full w-full object-cover"
        }
        onError={markFailed}
      />
    </button>
  );
}

/** Fullscreen original-image viewer. Loads `workspace_path`; download lives only here. */
function ChatImageLightbox({
  chatId,
  images,
  index,
  onClose,
  onIndexChange,
}: {
  chatId: string;
  images: StoredAttachment[];
  index: number;
  onClose: () => void;
  onIndexChange: (next: number) => void;
}) {
  const attachment = images[index];
  const originalPath = attachment?.workspace_path;
  const { url, status, markFailed } = useChatImageBlob(chatId, originalPath);
  const multi = images.length > 1;

  const goPrev = useCallback(() => {
    onIndexChange((index - 1 + images.length) % images.length);
  }, [index, images.length, onIndexChange]);

  const goNext = useCallback(() => {
    onIndexChange((index + 1) % images.length);
  }, [index, images.length, onIndexChange]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        onClose();
        return;
      }
      if (!multi) return;
      if (e.key === "ArrowLeft") goPrev();
      if (e.key === "ArrowRight") goNext();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose, multi, goPrev, goNext]);

  const handleDownload = () => {
    if (!originalPath || !attachment) return;
    void downloadChatAttachment(chatId, originalPath, attachment.name).catch(
      (e) => notifyActionError("下载失败", e),
    );
  };

  if (!attachment) return null;

  return createPortal(
    // biome-ignore lint/a11y/useSemanticElements: lightweight image lightbox — role="dialog" + Esc/backdrop close; native <dialog> would add modal/form semantics we don't need.
    <div
      role="dialog"
      aria-modal="true"
      aria-label={attachment.name || "图片"}
      className="fixed inset-0 z-50 flex flex-col bg-background/95"
    >
      <div className="flex h-12 shrink-0 items-center justify-between gap-2 border-border border-b px-4">
        <span className="min-w-0 truncate text-sm text-muted-foreground">
          {attachment.name}
          {multi ? ` · ${index + 1}/${images.length}` : ""}
        </span>
        <div className="flex shrink-0 items-center gap-1">
          <IconButton
            onClick={handleDownload}
            aria-label="下载原图"
            title="下载原图"
            disabled={!originalPath}
          >
            <Download size={16} />
          </IconButton>
          <IconButton onClick={onClose} aria-label="关闭" title="关闭">
            <X size={16} />
          </IconButton>
        </div>
      </div>

      <div className="relative flex min-h-0 flex-1 items-center justify-center">
        <button
          type="button"
          aria-label="关闭"
          className="absolute inset-0 cursor-zoom-out"
          onClick={onClose}
        />

        {multi && (
          <IconButton
            size="md"
            onClick={(e) => {
              e.stopPropagation();
              goPrev();
            }}
            aria-label="上一张"
            title="上一张"
            className="absolute left-3 z-10 bg-background/80"
          >
            <ChevronLeft size={18} />
          </IconButton>
        )}

        <div className="relative z-[1] flex max-h-full max-w-full items-center justify-center p-6">
          {status === "failed" && <FailedTile className="size-40 rounded-xl" />}
          {status === "loading" && (
            <LoadingTile className="size-40 rounded-xl" />
          )}
          {status === "ready" && url && (
            <img
              src={url}
              alt={attachment.name}
              className="max-h-[calc(100vh-5rem)] max-w-full object-contain"
              onError={markFailed}
            />
          )}
        </div>

        {multi && (
          <IconButton
            size="md"
            onClick={(e) => {
              e.stopPropagation();
              goNext();
            }}
            aria-label="下一张"
            title="下一张"
            className="absolute right-3 z-10 bg-background/80"
          >
            <ChevronRight size={18} />
          </IconButton>
        )}
      </div>
    </div>,
    document.body,
  );
}

/**
 * IM image attachments as a WeChat-style thumbnail grid. Click opens a portal
 * lightbox on the original (`workspace_path`); download lives only in the lightbox.
 */
export function ChatImageGallery({
  chatId,
  images,
}: {
  chatId: string;
  images: StoredAttachment[];
}) {
  const [lightboxIndex, setLightboxIndex] = useState<number | null>(null);
  const count = images.length;
  if (count === 0) return null;

  const gridClass =
    count === 1
      ? ""
      : count === 2
        ? "grid max-w-[260px] grid-cols-2 gap-1.5"
        : "grid max-w-[260px] grid-cols-3 gap-1";

  return (
    <>
      <div className={gridClass || undefined}>
        {images.map((a, i) => (
          <ChatImageThumb
            key={a.workspace_path ?? a.path}
            chatId={chatId}
            attachment={a}
            count={count}
            onOpen={() => setLightboxIndex(i)}
          />
        ))}
      </div>

      {lightboxIndex != null && (
        <ChatImageLightbox
          chatId={chatId}
          images={images}
          index={lightboxIndex}
          onClose={() => setLightboxIndex(null)}
          onIndexChange={setLightboxIndex}
        />
      )}
    </>
  );
}
