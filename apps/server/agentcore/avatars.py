"""Avatar (头像) image processing: normalise any upload to a small square WebP.

Re-encoding (rather than storing the raw upload) is what makes avatars safe and
cheap: it proves the bytes are a real image, strips EXIF/metadata, forces one
predictable format + size, and center-crops to a square so the circular UI never
distorts. A non-image (or a decompression-bomb) is rejected as a ValidationError
so the route returns 422 rather than persisting junk.
"""

from __future__ import annotations

import hashlib
import io

from PIL import Image, ImageOps, UnidentifiedImageError

from agentcore.core.errors import ValidationError

# Square edge of the stored avatar. 256px covers a ~128px display at 2x (retina);
# avatars render small, so a larger original buys nothing once re-encoded.
AVATAR_SIZE = 256
_WEBP_QUALITY = 82


def process_avatar(data: bytes) -> bytes:
    """Decode, square-crop, resize, and re-encode an avatar upload to WebP bytes.

    Raises ``ValidationError`` if the bytes are not a decodable image. Transparency
    is preserved (RGBA → WebP with alpha); EXIF orientation is honoured before the
    crop so a phone photo isn't sideways.
    """
    try:
        with Image.open(io.BytesIO(data)) as img:
            img = ImageOps.exif_transpose(img)
            has_alpha = img.mode in ("RGBA", "LA") or (
                img.mode == "P" and "transparency" in img.info
            )
            img = img.convert("RGBA" if has_alpha else "RGB")
            # fit = center-crop to the target aspect (square) then resize to exact size.
            square = ImageOps.fit(img, (AVATAR_SIZE, AVATAR_SIZE), Image.Resampling.LANCZOS)
            buffer = io.BytesIO()
            square.save(buffer, format="WEBP", quality=_WEBP_QUALITY, method=4)
            return buffer.getvalue()
    except (
        UnidentifiedImageError,
        OSError,
        ValueError,
        Image.DecompressionBombError,
    ) as e:
        raise ValidationError("无法识别的图片，请上传 PNG / JPEG / WebP 格式") from e


def avatar_key(user_id: str, processed: bytes) -> str:
    """The content-addressed storage key for a processed avatar.

    Hashing the *processed* bytes makes the key (and thus the served URL) stable
    for an identical result and fresh on any real change — so the frontend's cached
    ``<img>`` updates exactly when the picture does.
    """
    digest = hashlib.sha256(processed).hexdigest()[:16]
    return f"avatars/{user_id}/{digest}.webp"
