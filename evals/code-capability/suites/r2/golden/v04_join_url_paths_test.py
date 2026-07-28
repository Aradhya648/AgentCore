"""GOLDEN · flask.join_url_paths（R2 Extend；评测追加，勿改 upstream 测）."""

from flask import join_url_paths


def test_smoke_existing_url_for():
    from flask import url_for

    assert callable(url_for)


def test_join_url_paths():
    assert join_url_paths("api", "v1", "users") == "/api/v1/users"
    assert join_url_paths("/api/", "/v1/") == "/api/v1"
    assert join_url_paths() == "/"
    assert join_url_paths("", "/") == "/"
