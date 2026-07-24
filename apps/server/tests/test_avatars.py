"""Unit tests for avatar image processing (agentcore.avatars)."""

import io

import pytest
from PIL import Image

from agentcore.avatars import AVATAR_SIZE, avatar_key, process_avatar
from agentcore.core.errors import ValidationError


def _image_bytes(width: int, height: int, *, mode: str = "RGB", fmt: str = "PNG") -> bytes:
    color = (10, 120, 220, 128) if mode == "RGBA" else (10, 120, 220)
    img = Image.new(mode, (width, height), color)
    buffer = io.BytesIO()
    img.save(buffer, format=fmt)
    return buffer.getvalue()


def test_process_avatar_normalizes_to_square_webp():
    # A non-square JPEG should come back as a square WebP at the target size.
    out = process_avatar(_image_bytes(100, 240, fmt="JPEG"))
    with Image.open(io.BytesIO(out)) as img:
        assert img.format == "WEBP"
        assert img.size == (AVATAR_SIZE, AVATAR_SIZE)


def test_process_avatar_preserves_alpha():
    out = process_avatar(_image_bytes(64, 64, mode="RGBA"))
    with Image.open(io.BytesIO(out)) as img:
        assert img.format == "WEBP"
        assert "A" in img.getbands()


def test_process_avatar_rejects_non_image():
    with pytest.raises(ValidationError):
        process_avatar(b"this is plainly not an image")


def test_process_avatar_rejects_empty():
    with pytest.raises(ValidationError):
        process_avatar(b"")


def test_avatar_key_is_content_addressed_and_stable():
    processed = process_avatar(_image_bytes(80, 80))
    key1 = avatar_key("user-123", processed)
    key2 = avatar_key("user-123", processed)
    # Same bytes → same key (cacheable URL); namespaced by user; webp suffix.
    assert key1 == key2
    assert key1.startswith("avatars/user-123/")
    assert key1.endswith(".webp")


def test_avatar_key_changes_with_content():
    a = avatar_key("u", process_avatar(_image_bytes(80, 80)))
    b = avatar_key("u", process_avatar(_image_bytes(80, 80, mode="RGBA")))
    assert a != b
