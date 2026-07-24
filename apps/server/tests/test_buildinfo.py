"""Unit tests for build-provenance resolution at server launch."""

import os
import re

from agentcore import buildinfo


def test_respects_injected_environment(monkeypatch):
    # Pipeline-stamped values must win and git must not even be consulted.
    monkeypatch.setenv("GIT_SHA", "deadbee")
    monkeypatch.setenv("BUILT_AT", "2026-01-02T03:04:05Z")

    def _fail() -> str | None:
        raise AssertionError("git must not be consulted when GIT_SHA is set")

    monkeypatch.setattr(buildinfo, "_git_short_sha", _fail)

    buildinfo.resolve_build_provenance()

    assert os.environ["GIT_SHA"] == "deadbee"
    assert os.environ["BUILT_AT"] == "2026-01-02T03:04:05Z"


def test_fills_from_working_tree_when_unset(monkeypatch):
    monkeypatch.delenv("GIT_SHA", raising=False)
    monkeypatch.delenv("BUILT_AT", raising=False)
    monkeypatch.setattr(buildinfo, "_git_short_sha", lambda: "abc1234")

    buildinfo.resolve_build_provenance()

    assert os.environ["GIT_SHA"] == "abc1234"
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", os.environ["BUILT_AT"])


def test_leaves_git_sha_unset_when_unavailable(monkeypatch):
    # No git → GIT_SHA stays unset so config falls back to its "unknown" default;
    # BUILT_AT is still stamped at launch time.
    monkeypatch.delenv("GIT_SHA", raising=False)
    monkeypatch.delenv("BUILT_AT", raising=False)
    monkeypatch.setattr(buildinfo, "_git_short_sha", lambda: None)

    buildinfo.resolve_build_provenance()

    assert "GIT_SHA" not in os.environ
    assert os.environ["BUILT_AT"].endswith("Z")
