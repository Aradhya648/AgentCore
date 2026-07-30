import {
  type StoredAttachment,
  fetchChatAttachmentBlob,
} from "@/api/messaging";
import { Modal } from "@/components/Modal";
import { canShareFiles, downloadBlob, shareOrDownloadFile } from "@/lib/share";
import { ChevronLeft, ChevronRight, ImageOff, Loader2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";

type ImageStatus = "loading" | "ready" | "failed";

/**
 * Bearer-authed fetch → object URL for an IM attachment path. Fetch rejection and
 * `<img onError>` both land on `failed` — no silent `.catch(() => {})`.
 *
 * When `fallbackPath` is set (bubble preview: thumb → original), a failed primary
 * fetch retries the fallback once before surfacing ImageOff.
 */
function useChatImageBlob(
  chatId: string,
  path: string | null | undefined,
  fallbackPath?: string | null,
): {
  url: string | null;
  blob: Blob | null;
  status: ImageStatus;
  markFailed: () => void;
} {
  const [url, setUrl] = useState<string | null>(null);
  const [blob, setBlob] = useState<Blob | null>(null);
  const [status, setStatus] = useState<ImageStatus>("loading");

  useEffect(() => {
    if (!path) {
      setUrl(null);
      setBlob(null);
      setStatus("failed");
      return;
    }
    let active = true;
    let objectUrl: string | null = null;
    setUrl(null);
    setBlob(null);
    setStatus("loading");

    const load = (candidate: string, allowFallback: boolean) =>
      fetchChatAttachmentBlob(chatId, candidate)
        .then((b) => {
          if (!active) return;
          objectUrl = URL.createObjectURL(b);
          setBlob(b);
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
          setBlob(null);
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

  return { url, blob, status, markFailed };
}

function FailedTile({ className }: { className?: string }) {
  return (
    <div
      className={`im-img-failed ${className ?? ""}`}
      role="img"
      aria-label="图片加载失败"
    >
      <ImageOff size={18} aria-hidden />
      <span>加载失败</span>
    </div>
  );
}

function LoadingTile({ className }: { className?: string }) {
  return (
    <div className={`im-img-loading ${className ?? ""}`} aria-hidden>
      <Loader2 size={16} className="voice-spin" />
    </div>
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
      ? "im-img-tile solo"
      : count === 2
        ? "im-img-tile duo"
        : "im-img-tile multi";

  if (status === "failed") {
    return <FailedTile className={tileClass} />;
  }
  if (status === "loading" || !url) {
    return <LoadingTile className={tileClass} />;
  }

  return (
    <button
      type="button"
      className={`im-attach-img-btn ${tileClass}`}
      onClick={onOpen}
      title={attachment.name}
      aria-label={`查看 ${attachment.name}`}
    >
      <img
        className="im-attach-img"
        src={url}
        alt={attachment.name}
        onError={markFailed}
      />
    </button>
  );
}

/** Fullscreen original-image viewer via native Modal (`className="viewer"`). */
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
  const originalPath = attachment?.workspace_path ?? null;
  const { url, blob, status, markFailed } = useChatImageBlob(
    chatId,
    originalPath,
  );
  const multi = images.length > 1;
  const sharable = canShareFiles();
  const [actionError, setActionError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const goPrev = useCallback(() => {
    onIndexChange((index - 1 + images.length) % images.length);
  }, [index, images.length, onIndexChange]);

  const goNext = useCallback(() => {
    onIndexChange((index + 1) % images.length);
  }, [index, images.length, onIndexChange]);

  useEffect(() => {
    if (!multi) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "ArrowLeft") goPrev();
      if (e.key === "ArrowRight") goNext();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [multi, goPrev, goNext]);

  // biome-ignore lint/correctness/useExhaustiveDependencies: index is an intentional re-run key — clear share/save errors when the lightbox slide changes.
  useEffect(() => {
    setActionError(null);
  }, [index]);

  if (!attachment) return null;

  async function share() {
    if (!blob || busy) return;
    setBusy(true);
    setActionError(null);
    try {
      await shareOrDownloadFile(blob, attachment.name, blob.type);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "分享失败");
    } finally {
      setBusy(false);
    }
  }

  function save() {
    if (!blob || busy) return;
    setActionError(null);
    try {
      downloadBlob(blob, attachment.name);
    } catch (e) {
      setActionError(e instanceof Error ? e.message : "下载失败");
    }
  }

  const title =
    multi && attachment.name
      ? `${attachment.name} · ${index + 1}/${images.length}`
      : attachment.name || "图片";

  return (
    <Modal className="viewer" onClose={onClose} label={title}>
      <header className="bar">
        <button type="button" className="link" onClick={onClose}>
          ← 关闭
        </button>
        <span className="viewer-name">{title}</span>
        <span className="bar-right">
          {sharable && (
            <button
              type="button"
              className="link"
              onClick={() => void share()}
              disabled={!blob || busy}
            >
              分享
            </button>
          )}
          <button
            type="button"
            className="link"
            onClick={save}
            disabled={!blob || busy}
            aria-label="下载原图"
          >
            下载
          </button>
        </span>
      </header>
      <div className="viewer-body im-lightbox-body">
        {status === "loading" && (
          <p className="muted hint">
            <Loader2 size={16} className="voice-spin" aria-hidden /> 加载中…
          </p>
        )}
        {status === "failed" && <FailedTile className="im-lightbox-failed" />}
        {status === "ready" && url && (
          <img
            className="viewer-img"
            src={url}
            alt={attachment.name}
            onError={markFailed}
          />
        )}
        {actionError && <p className="error hint">{actionError}</p>}
        {multi && (
          <>
            <button
              type="button"
              className="im-lightbox-nav prev"
              onClick={goPrev}
              aria-label="上一张"
            >
              <ChevronLeft size={22} aria-hidden />
            </button>
            <button
              type="button"
              className="im-lightbox-nav next"
              onClick={goNext}
              aria-label="下一张"
            >
              <ChevronRight size={22} aria-hidden />
            </button>
          </>
        )}
      </div>
    </Modal>
  );
}

/**
 * IM image attachments as a WeChat-style thumbnail grid. Click opens a Modal
 * lightbox on the original (`workspace_path`); share/download live only there.
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
      ? "im-img-grid cols-1"
      : count === 2
        ? "im-img-grid cols-2"
        : "im-img-grid cols-3";

  return (
    <>
      <div className={gridClass}>
        {images.map((a, i) => (
          <ChatImageThumb
            key={a.workspace_path ?? `${a.name}-${i}`}
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
