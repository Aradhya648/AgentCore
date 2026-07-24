"""Unit tests for RFC 5987 download Content-Disposition headers."""

from urllib.parse import unquote

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
