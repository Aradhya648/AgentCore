"""Bounded WebP thumbnails for IM image attachments (Stage 4 富消息).

Re-encodes an uploaded image to a small WebP so a chat thread can show inline
previews cheaply instead of streaming full-resolution originals (the bandwidth
win). Best-effort by contract: a non-image, an animated GIF (a static thumbnail
would drop its animation), an already-small image, or any decode/encode failure
returns ``None`` and the caller serves the original — generating a preview must
never break an otherwise-valid upload.
"""

from __future__ import annotations

import io

from agentcore.core.logging import get_logger

logger = get_logger(__name__)

# Longest-edge cap for a generated thumbnail. 512px covers the bubble's ~260px
# display at 2x (retina) with headroom; the aspect ratio is preserved.
THUMBNAIL_MAX_EDGE = 512
_WEBP_QUALITY = 80


def make_image_thumbnail(data: bytes) -> bytes | None:
    """Return WebP thumbnail bytes for an image, or ``None`` to use the original.

    ``None`` means "serve the original inline": the bytes are not a decodable
    image, are an animated GIF, are already within :data:`THUMBNAIL_MAX_EDGE`, or
    failed to process. Transparency is preserved (RGBA → WebP with alpha).

    Pillow is imported lazily so the messaging package can load without Pillow —
    required for the sidecar import closure (Pillow is not in the sidecar subset).
    """
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError:
        logger.debug("messaging.thumbnail_pillow_missing")
        return None

    try:
        with Image.open(io.BytesIO(data)) as img:
            fmt = (img.format or "").upper()
            # An animated GIF would lose its animation as a static thumbnail —
            # keep the original inline (click-through still has the full file).
            if fmt == "GIF" and getattr(img, "is_animated", False):
                return None
            if max(img.size) <= THUMBNAIL_MAX_EDGE:
                return None  # already small; a thumbnail would save nothing
            has_alpha = img.mode in ("RGBA", "LA") or (
                img.mode == "P" and "transparency" in img.info
            )
            resized = img.convert("RGBA" if has_alpha else "RGB")
            resized.thumbnail((THUMBNAIL_MAX_EDGE, THUMBNAIL_MAX_EDGE), Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            resized.save(buffer, format="WEBP", quality=_WEBP_QUALITY, method=4)
            return buffer.getvalue()
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as e:
        # Bad bytes, an unsupported codec, or a decompression-bomb guard trip:
        # log and fall back to the original (never fail the upload over a preview).
        logger.warning("chat.thumbnail_failed", error=str(e))
        return None
