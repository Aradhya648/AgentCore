"""Tests for Windows-safe log rotation (no silent drop on rollover failure)."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import patch

import pytest

from agentcore.core.logging import (
    ROLLOVER_FAILED_EVENT,
    ResilientRotatingFileHandler,
)


def _record(msg: str = "hello") -> logging.LogRecord:
    return logging.LogRecord(
        name="test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )


def _boom_do_rollover(handler: ResilientRotatingFileHandler) -> None:
    if handler.stream:
        handler.stream.close()
        handler.stream = None
    raise PermissionError(32, "file in use by another process")


def test_rename_failure_falls_back_to_copy_truncate(tmp_path: Path) -> None:
    """rename doRollover fails → copy-truncate produces .1 and shrinks primary."""
    path = tmp_path / "dev.jsonl"
    seed = "x" * 200 + "\n"
    path.write_text(seed, encoding="utf-8")
    before_size = path.stat().st_size
    handler = ResilientRotatingFileHandler(
        path,
        maxBytes=100,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))

    with patch.object(handler, "doRollover", side_effect=lambda: _boom_do_rollover(handler)):
        handler.emit(_record("after-copy-truncate"))

    handler.close()
    backup = tmp_path / "dev.jsonl.1"
    assert backup.exists()
    assert "x" * 200 in backup.read_text(encoding="utf-8")
    main = path.read_text(encoding="utf-8")
    assert "after-copy-truncate" in main
    assert path.stat().st_size < before_size
    assert ROLLOVER_FAILED_EVENT not in main
    assert not (tmp_path / "dev.jsonl.rotate.lock").exists()


def test_unrecoverable_rollover_still_writes_and_alerts(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = tmp_path / "dev.jsonl"
    path.write_text("x" * 200 + "\n", encoding="utf-8")
    handler = ResilientRotatingFileHandler(
        path,
        maxBytes=100,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))

    with (
        patch.object(handler, "doRollover", side_effect=lambda: _boom_do_rollover(handler)),
        patch.object(handler, "_copy_truncate_rollover", return_value="failed"),
    ):
        handler.emit(_record("kept-after-failed-rollover"))
        # Second emit while oversized: still must not drop (backoff skips retry).
        handler.emit(_record("kept-while-backoff"))

    handler.close()
    text = path.read_text(encoding="utf-8")
    assert "kept-after-failed-rollover" in text
    assert "kept-while-backoff" in text
    assert ROLLOVER_FAILED_EVENT in text
    err = capsys.readouterr().err
    assert ROLLOVER_FAILED_EVENT in err
    assert "journal" in err.lower()
    # Alert once per failure window (not once per emit).
    assert text.count(ROLLOVER_FAILED_EVENT) == 1


def test_rotate_lock_busy_reopens_without_alert(tmp_path: Path) -> None:
    path = tmp_path / "dev.jsonl"
    path.write_text("x" * 200 + "\n", encoding="utf-8")
    lock_path = path.with_name(path.name + ".rotate.lock")
    lock_path.write_text("held", encoding="utf-8")
    handler = ResilientRotatingFileHandler(
        path,
        maxBytes=100,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))

    with patch.object(handler, "doRollover", side_effect=lambda: _boom_do_rollover(handler)):
        handler.emit(_record("kept-while-peer-rotates"))

    handler.close()
    text = path.read_text(encoding="utf-8")
    assert "kept-while-peer-rotates" in text
    assert ROLLOVER_FAILED_EVENT not in text
    assert not (tmp_path / "dev.jsonl.1").exists()
    assert lock_path.exists()  # peer lock left alone


def test_copy_truncate_releases_lock_on_failure(tmp_path: Path) -> None:
    path = tmp_path / "dev.jsonl"
    path.write_text("x" * 200 + "\n", encoding="utf-8")
    handler = ResilientRotatingFileHandler(
        path,
        maxBytes=100,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    lock_path = path.with_name(path.name + ".rotate.lock")

    with (
        patch.object(handler, "doRollover", side_effect=lambda: _boom_do_rollover(handler)),
        patch.object(
            handler,
            "_rotate_backups_by_copy",
            side_effect=OSError(5, "copy failed"),
        ),
    ):
        handler.emit(_record("kept-after-copy-fail"))

    handler.close()
    assert "kept-after-copy-fail" in path.read_text(encoding="utf-8")
    assert not lock_path.exists()
    assert ROLLOVER_FAILED_EVENT in path.read_text(encoding="utf-8")


def test_stdlib_rotating_handler_drops_on_same_failure(tmp_path: Path) -> None:
    """Document the stdlib failure mode we are fixing (baseline regression)."""
    from logging.handlers import RotatingFileHandler

    path = tmp_path / "dev.jsonl"
    path.write_text("x" * 200 + "\n", encoding="utf-8")
    handler = RotatingFileHandler(path, maxBytes=100, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(message)s"))

    def _boom() -> None:
        if handler.stream:
            handler.stream.close()
            handler.stream = None
        raise PermissionError(32, "file in use by another process")

    with patch.object(handler, "doRollover", side_effect=_boom):
        handler.emit(_record("lost-by-stdlib"))

    handler.close()
    text = path.read_text(encoding="utf-8")
    assert "lost-by-stdlib" not in text


def test_successful_rollover_still_produces_backup(tmp_path: Path) -> None:
    path = tmp_path / "dev.jsonl"
    path.write_text("seed\n", encoding="utf-8")
    handler = ResilientRotatingFileHandler(
        path,
        maxBytes=20,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.emit(_record("aaaaaaaaaaaaaaaaaaaa"))  # force rollover
    handler.emit(_record("after-rotate"))
    handler.close()

    backup = tmp_path / "dev.jsonl.1"
    assert backup.exists()
    assert "after-rotate" in path.read_text(encoding="utf-8")


def test_backoff_retries_rollover_after_window(tmp_path: Path) -> None:
    path = tmp_path / "dev.jsonl"
    path.write_text("x" * 200 + "\n", encoding="utf-8")
    handler = ResilientRotatingFileHandler(
        path,
        maxBytes=100,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(logging.Formatter("%(message)s"))
    calls = {"n": 0}

    def _boom() -> None:
        calls["n"] += 1
        if handler.stream:
            handler.stream.close()
            handler.stream = None
        raise PermissionError(32, "busy")

    with (
        patch.object(handler, "doRollover", side_effect=_boom),
        patch.object(handler, "_copy_truncate_rollover", return_value="failed"),
    ):
        handler.emit(_record("one"))
        assert calls["n"] == 1
        handler.emit(_record("two"))
        assert calls["n"] == 1  # still in backoff
        # Expire backoff and ensure we retry.
        handler._rollover_retry_after = 0.0
        handler.emit(_record("three"))
        assert calls["n"] == 2

    handler.close()
    body = path.read_text(encoding="utf-8")
    assert "one" in body and "two" in body and "three" in body
    # Alert JSONL lines are parseable.
    for line in body.splitlines():
        if ROLLOVER_FAILED_EVENT in line and line.strip().startswith("{"):
            obj = json.loads(line)
            assert obj["event"] == ROLLOVER_FAILED_EVENT
            assert obj["hint"] == "journal_is_source_of_truth"


def test_module_import_ok() -> None:
    import agentcore.core.logging as logging_mod

    assert hasattr(logging_mod, "ResilientRotatingFileHandler")
    assert hasattr(logging_mod, "setup_logging")
