"""Unit tests for RFC 5987 download Content-Disposition headers."""

from urllib.parse import unquote

import pytest

from agentcore.api.download_headers import download_headers


def test_download_headers_ascii_filename():
    headers = download_headers("hello.bin")
    cd = headers["Content-Disposition"]
    assert 'filename="hello.bin"' in cd
    assert "filename*=UTF-8''hello.bin" in cd


def test_download_headers_chinese_filename_uses_rfc5987():
    """Bare filename= with Chinese would latin-1-crash Starlette; filename* carries it."""
    name = "报告-终稿.xlsx"
    headers = download_headers(name)
    cd = headers["Content-Disposition"]
    assert "filename*=UTF-8''" in cd
    encoded = cd.split("filename*=UTF-8''", 1)[1]
    assert unquote(encoded) == name
    # ASCII fallback must be latin-1 safe (no CJK left after ignore).
    assert 'filename="' in cd
    ascii_part = cd.split('filename="', 1)[1].split('"', 1)[0]
    ascii_part.encode("latin-1")


def test_download_headers_all_non_ascii_falls_back():
    headers = download_headers("中文名", fallback="download")
    cd = headers["Content-Disposition"]
    assert 'filename="download"' in cd
    assert unquote(cd.split("filename*=UTF-8''", 1)[1]) == "中文名"


def test_download_headers_inline_disposition_for_im_preview():
    """IM blob fetch uses inline; must still be latin-1-safe with CJK names."""
    name = "微信图片.jpg"
    headers = download_headers(name, disposition="inline")
    cd = headers["Content-Disposition"]
    assert cd.startswith("inline;")
    cd.encode("latin-1")  # Starlette ASGI header encode
    assert unquote(cd.split("filename*=UTF-8''", 1)[1]) == name


def test_inline_response_with_cjk_filename_survives_asgi_encode():
    """Regression: bare filename=\"微信…\" latin-1-crashes ASGI → IM ImageOff."""
    from starlette.responses import Response

    name = "截图.png.thumb.webp"
    r = Response(
        content=b"webp",
        media_type="image/webp",
        headers=download_headers(name, disposition="inline"),
    )
    for key, value in r.headers.items():
        key.encode("latin-1")
        value.encode("latin-1")


def test_bare_inline_filename_with_cjk_still_crashes_asgi():
    """Document the pre-fix failure mode so we don't regress to it."""
    from starlette.responses import Response

    with pytest.raises(UnicodeEncodeError):
        Response(
            content=b"x",
            headers={"Content-Disposition": 'inline; filename="微信图片.jpg"'},
        )
