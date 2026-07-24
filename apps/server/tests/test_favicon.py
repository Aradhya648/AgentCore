"""Tests for the favicon proxy route — pure helpers + the handler's cache/404 logic.

No real network: the handler's network step (``_resolve_favicon``) is monkeypatched,
so these assert the domain normalization, image sniffing, ``<link rel=icon>`` parsing,
the in-process positive/negative cache, and the 404-on-miss contract.
"""

import pytest

from agentcore.api.routes import favicon as fav


@pytest.fixture(autouse=True)
def _clear_cache():
    fav._cache.clear()
    yield
    fav._cache.clear()


# --- _normalize_domain ---


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("example.com", "example.com"),
        ("EXAMPLE.com", "example.com"),
        ("https://example.com/path?q=1", "example.com"),
        ("http://sub.example.com", "sub.example.com"),
        ("example.com/", "example.com"),
        ("  example.com.  ", "example.com"),
        ("", None),
        ("localhost-no-dot", None),
        ("has space.com", None),
        ("a" * 254 + ".com", None),
    ],
)
def test_normalize_domain(raw, expected):
    assert fav._normalize_domain(raw) == expected


# --- _sniff_media_type ---


def test_sniff_png_by_magic():
    assert fav._sniff_media_type(b"\x89PNG\r\n\x1a\n....", "text/plain") == "image/png"


def test_sniff_ico_by_magic_even_with_wrong_header():
    # Servers often mislabel favicon.ico; the bytes win.
    assert fav._sniff_media_type(b"\x00\x00\x01\x00rest", "text/html") == "image/x-icon"


def test_sniff_svg_by_header():
    svg = b"<svg xmlns='...'></svg>"
    assert fav._sniff_media_type(svg, "image/svg+xml; charset=utf-8") == "image/svg+xml"


def test_sniff_rejects_html_page():
    assert fav._sniff_media_type(b"<!DOCTYPE html><html>404</html>", "text/html") is None


def test_sniff_trusts_image_header_for_unknown_bytes():
    assert fav._sniff_media_type(b"\x01\x02\x03\x04unknown", "image/webp") == "image/webp"


def test_sniff_rejects_unknown_bytes_without_image_header():
    assert fav._sniff_media_type(b"\x01\x02\x03\x04unknown", "application/json") is None


# --- _IconLinkParser ---


def test_icon_link_parser_collects_icon_rels_only():
    html = (
        "<head>"
        '<link rel="stylesheet" href="/s.css">'
        '<link rel="icon" href="/fav.png">'
        '<link rel="shortcut icon" href="/legacy.ico">'
        '<link rel="apple-touch-icon" href="/touch.png">'
        '<link rel="icon">'  # no href → ignored
        "</head>"
    )
    parser = fav._IconLinkParser()
    parser.feed(html)
    assert parser.hrefs == ["/fav.png", "/legacy.ico", "/touch.png"]


# --- cache ---


def test_cache_put_get_roundtrip_and_negative():
    fav._cache_put("a.com", b"png", "image/png", ttl=100)
    entry = fav._cache_get("a.com")
    assert entry is not None and entry.data == b"png" and entry.media_type == "image/png"

    fav._cache_put("miss.com", None, "", ttl=100)
    neg = fav._cache_get("miss.com")
    assert neg is not None and neg.data is None


def test_cache_expiry_evicts():
    fav._cache_put("old.com", b"x", "image/png", ttl=-1)  # already expired
    assert fav._cache_get("old.com") is None
    assert "old.com" not in fav._cache


# --- get_favicon handler ---


async def test_favicon_invalid_domain_404():
    resp = await fav.get_favicon(domain="not-a-domain")
    assert resp.status_code == 404


async def test_favicon_hit_returns_image_and_caches(monkeypatch):
    calls = {"n": 0}

    async def fake_resolve(domain: str):
        calls["n"] += 1
        return (b"\x89PNG\r\n\x1a\nbytes", "image/png")

    monkeypatch.setattr(fav, "_resolve_favicon", fake_resolve)

    resp = await fav.get_favicon(domain="example.com")
    assert resp.status_code == 200
    assert resp.body == b"\x89PNG\r\n\x1a\nbytes"
    assert resp.media_type == "image/png"
    assert "max-age" in resp.headers.get("cache-control", "")

    # Second call is served from cache (resolver not invoked again).
    resp2 = await fav.get_favicon(domain="example.com")
    assert resp2.status_code == 200
    assert calls["n"] == 1


async def test_favicon_miss_404_and_negative_cached(monkeypatch):
    calls = {"n": 0}

    async def fake_resolve(domain: str):
        calls["n"] += 1
        return None

    monkeypatch.setattr(fav, "_resolve_favicon", fake_resolve)

    resp = await fav.get_favicon(domain="nope.com")
    assert resp.status_code == 404

    # Negative cache → no second network attempt.
    resp2 = await fav.get_favicon(domain="nope.com")
    assert resp2.status_code == 404
    assert calls["n"] == 1
