/**
 * Image element support (AI协作白板.md §九 截图/手绘走视觉).
 *
 * Two concerns kept out of the pure-sync renderer: (1) {@link ImageCache} — an
 * async-decoding cache the renderer pulls decoded `<img>`s from; (2) {@link loadImageForImport}
 * — turns a pasted / dropped file into a size-bounded data URL the engine stores on an
 * `image` element. Images live in pixels → the AI reads them via vision (`board_read`),
 * never as text, which is why `image` joins `freedraw` in the「整理选区」visual set.
 */

/** Longest-side cap (px) for an imported image's stored data URL — bounds the scene blob
 * that autosaves to Postgres so a few screenshots don't bloat every save (§九.2 体积护栏). */
export const MAX_IMAGE_DIM = 1024;

export interface ImportedImage {
  /** Data URL (base64) stored on the element's `src`. */
  src: string;
  /** Natural (possibly downscaled) pixel size — the engine seeds the element box from it. */
  w: number;
  h: number;
}

/**
 * Decode a pasted / dropped image blob into a bounded data URL + its pixel size.
 *
 * Images within {@link MAX_IMAGE_DIM} keep their original bytes; larger ones are redrawn
 * onto an offscreen canvas at the cap (re-encoded PNG) to keep the persisted scene small.
 * Rejects on a non-image / undecodable blob — the caller swallows it (no element added).
 */
export async function loadImageForImport(
  blob: Blob,
  maxDim = MAX_IMAGE_DIM,
): Promise<ImportedImage> {
  const dataUrl = await blobToDataUrl(blob);
  const img = await decodeDataUrl(dataUrl);
  const nw = img.naturalWidth || img.width;
  const nh = img.naturalHeight || img.height;
  if (nw <= 0 || nh <= 0) throw new Error("无法解码图片尺寸");

  const scale = Math.min(1, maxDim / Math.max(nw, nh));
  if (scale >= 1) return { src: dataUrl, w: nw, h: nh };

  const w = Math.max(1, Math.round(nw * scale));
  const h = Math.max(1, Math.round(nh * scale));
  const off = document.createElement("canvas");
  off.width = w;
  off.height = h;
  const ctx = off.getContext("2d");
  if (!ctx) throw new Error("无法创建离屏画布上下文");
  ctx.drawImage(img, 0, 0, w, h);
  return { src: off.toDataURL("image/png"), w, h };
}

function blobToDataUrl(blob: Blob): Promise<string> {
  return new Promise((resolve, reject) => {
    const reader = new FileReader();
    reader.onload = () => resolve(reader.result as string);
    reader.onerror = () => reject(reader.error ?? new Error("读取图片失败"));
    reader.readAsDataURL(blob);
  });
}

function decodeDataUrl(src: string): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("图片解码失败"));
    img.src = src;
  });
}

/**
 * Lazily decodes data-URL images for the renderer. {@link get} returns a decoded `<img>`
 * once ready (else `null` → the renderer draws a placeholder), kicking off the decode on
 * first ask and calling `onLoad` (→ engine re-render) when it finishes. Keyed by the `src`
 * string, so an image shared across elements decodes once; a decode failure is remembered
 * so we never thrash retrying a broken src.
 */
export class ImageCache {
  private readonly cache = new Map<string, HTMLImageElement>();
  private readonly failed = new Set<string>();

  constructor(private readonly onLoad: () => void) {}

  get(src: string | undefined): HTMLImageElement | null {
    if (!src || this.failed.has(src)) return null;
    const existing = this.cache.get(src);
    if (existing) {
      return existing.complete && existing.naturalWidth > 0 ? existing : null;
    }
    const img = new Image();
    img.onload = () => this.onLoad();
    img.onerror = () => {
      this.failed.add(src);
      this.cache.delete(src);
    };
    img.src = src;
    this.cache.set(src, img);
    return img.complete && img.naturalWidth > 0 ? img : null;
  }
}
