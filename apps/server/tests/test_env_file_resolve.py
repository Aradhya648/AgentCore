"""Unit tests for AGENTCORE_ENV → env file selection (mocked paths)."""

from pathlib import Path

from agentcore.config.paths import resolve_env_file


def test_development_always_uses_dot_env(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("X=1\n", encoding="utf-8")
    (tmp_path / ".env.development").write_text("X=2\n", encoding="utf-8")
    assert resolve_env_file("development", server_dir=tmp_path) == tmp_path / ".env"


def test_non_development_prefers_specific_file(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("X=1\n", encoding="utf-8")
    (tmp_path / ".env.staging").write_text("X=2\n", encoding="utf-8")
    assert resolve_env_file("staging", server_dir=tmp_path) == tmp_path / ".env.staging"


def test_non_development_falls_back_when_missing(tmp_path: Path) -> None:
    (tmp_path / ".env").write_text("X=1\n", encoding="utf-8")
    assert resolve_env_file("staging", server_dir=tmp_path) == tmp_path / ".env"


def test_blank_name_defaults_to_development(tmp_path: Path, monkeypatch) -> None:
    monkeypatch.delenv("AGENTCORE_ENV", raising=False)
    (tmp_path / ".env").write_text("X=1\n", encoding="utf-8")
    assert resolve_env_file("", server_dir=tmp_path) == tmp_path / ".env"
    assert resolve_env_file(server_dir=tmp_path) == tmp_path / ".env"


def test_reads_agentcore_env_from_process(tmp_path: Path, monkeypatch) -> None:
    (tmp_path / ".env").write_text("X=1\n", encoding="utf-8")
    (tmp_path / ".env.ci").write_text("X=2\n", encoding="utf-8")
    monkeypatch.setenv("AGENTCORE_ENV", "ci")
    assert resolve_env_file(server_dir=tmp_path) == tmp_path / ".env.ci"
