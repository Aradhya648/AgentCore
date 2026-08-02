"""产物写回 staging（gVisor copy-in / copy-out）单元测试 — OS 无关的纯文件系统逻辑。

Windows 本地跑不了 gVisor 本体（runsc Linux-only），写回机制因此抽成纯函数：
staging 拷贝、变更收集、限额写回在这里全量覆盖；真沙箱端到端属部署后人工清单。
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

from agentcore.core.errors import SandboxError
from agentcore.tools.sandbox.staging import (
    SANDBOX_OCI_GID,
    SANDBOX_OCI_UID,
    collect_changes,
    prepare_bind_tree_for_sandbox,
    snapshot_tree,
    stage_workspace,
    write_back,
)


def _make_symlink_or_skip(target: Path, link: Path) -> None:
    try:
        os.symlink(str(target), str(link))
    except (OSError, NotImplementedError):
        pytest.skip("symlink not permitted on this host")


def test_stage_copies_tree_and_returns_baseline(tmp_path: Path):
    src = tmp_path / "ws"
    (src / "sub").mkdir(parents=True)
    (src / "a.txt").write_text("hello", encoding="utf-8")
    (src / "sub" / "b.csv").write_text("1,2", encoding="utf-8")
    (src / "empty").mkdir()

    dst = tmp_path / "staged"
    baseline = stage_workspace(src, dst, max_bytes=1024 * 1024)

    assert (dst / "a.txt").read_text(encoding="utf-8") == "hello"
    assert (dst / "sub" / "b.csv").read_text(encoding="utf-8") == "1,2"
    assert (dst / "empty").is_dir()  # empty dirs preserved
    assert set(baseline) == {"a.txt", "sub/b.csv"}


def test_stage_rejects_oversized_workspace_with_explainable_error(tmp_path: Path):
    src = tmp_path / "ws"
    src.mkdir()
    (src / "big.bin").write_bytes(b"x" * 2048)

    with pytest.raises(SandboxError) as ei:
        stage_workspace(src, tmp_path / "staged", max_bytes=1024)
    assert "工作区过大" in str(ei.value)
    assert "bind_local_folder" in str(ei.value)
    assert "勿用纯文本" in str(ei.value)


def test_stage_excludes_internal_zone_and_symlinks(tmp_path: Path):
    src = tmp_path / "ws"
    (src / "AgentCore" / "trash").mkdir(parents=True)
    (src / "AgentCore" / "trash" / "junk.txt").write_text("x", encoding="utf-8")
    (src / "AgentCore" / "index").mkdir(parents=True)
    (src / "AgentCore" / "index" / "code_search.db").write_bytes(b"db")
    (src / "AgentCore" / "规则").mkdir(parents=True)
    (src / "AgentCore" / "规则" / "x.md").write_text("rule", encoding="utf-8")
    (src / "AgentCore" / "记忆").mkdir(parents=True)
    (src / "AgentCore" / "记忆" / "y.md").write_text("mem", encoding="utf-8")
    (src / "AgentCore" / "文档").mkdir(parents=True)
    (src / "AgentCore" / "文档" / "z.md").write_text("doc", encoding="utf-8")
    (src / "real.txt").write_text("keep", encoding="utf-8")
    _make_symlink_or_skip(src / "real.txt", src / "link.txt")

    dst = tmp_path / "staged"
    baseline = stage_workspace(src, dst, max_bytes=1024 * 1024)

    assert not (dst / "AgentCore" / "trash").exists()
    assert not (dst / "AgentCore" / "index").exists()
    assert (dst / "AgentCore" / "规则" / "x.md").read_text(encoding="utf-8") == "rule"
    assert (dst / "AgentCore" / "记忆" / "y.md").read_text(encoding="utf-8") == "mem"
    assert (dst / "AgentCore" / "文档" / "z.md").read_text(encoding="utf-8") == "doc"
    assert not (dst / "link.txt").exists()
    assert set(baseline) == {
        "real.txt",
        "AgentCore/规则/x.md",
        "AgentCore/记忆/y.md",
        "AgentCore/文档/z.md",
    }


def test_collect_changes_reports_new_and_modified_only(tmp_path: Path):
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / "keep.txt").write_text("same", encoding="utf-8")
    (staged / "edit.txt").write_text("v1", encoding="utf-8")
    before = snapshot_tree(staged)

    (staged / "edit.txt").write_text("v2-longer", encoding="utf-8")
    (staged / "out").mkdir()
    (staged / "out" / "chart.png").write_bytes(b"\x89PNG")

    assert collect_changes(staged, before) == ["edit.txt", "out/chart.png"]


def test_write_back_lands_changes_and_never_propagates_deletes(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "original.txt").write_text("keep me", encoding="utf-8")

    staged = tmp_path / "staged"
    (staged / "out").mkdir(parents=True)
    (staged / "out" / "course.pptx").write_bytes(b"PK-pptx")
    (staged / "edit.txt").write_text("updated", encoding="utf-8")
    # 模拟沙箱内删除 original.txt：staging 里不存在 → 不进 changes → 工作区原件保留。

    report = write_back(
        staged,
        ws,
        ["edit.txt", "out/course.pptx"],
        max_bytes=1024 * 1024,
        max_files=10,
    )

    assert report.written == ["edit.txt", "out/course.pptx"]
    assert report.skipped == []
    assert (ws / "out" / "course.pptx").read_bytes() == b"PK-pptx"
    assert (ws / "edit.txt").read_text(encoding="utf-8") == "updated"
    assert (ws / "original.txt").read_text(encoding="utf-8") == "keep me"


def test_write_back_enforces_byte_and_file_caps(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / "small.txt").write_text("ok", encoding="utf-8")
    (staged / "big.bin").write_bytes(b"x" * 4096)
    (staged / "extra.txt").write_text("x", encoding="utf-8")

    report = write_back(
        staged,
        ws,
        ["big.bin", "extra.txt", "small.txt"],
        max_bytes=1024,  # big.bin exceeds remaining budget
        max_files=1,  # only one file may land
    )

    assert report.written == ["extra.txt"]
    assert sorted(report.skipped) == ["big.bin", "small.txt"]
    assert not (ws / "big.bin").exists()


def test_write_back_refuses_internal_zone_paths(tmp_path: Path):
    ws = tmp_path / "ws"
    ws.mkdir()
    staged = tmp_path / "staged"
    (staged / "AgentCore" / "trash").mkdir(parents=True)
    (staged / "AgentCore" / "trash" / "sneak.txt").write_text("x", encoding="utf-8")
    (staged / "AgentCore" / "规则").mkdir(parents=True)
    (staged / "AgentCore" / "规则" / "ok.md").write_text("ok", encoding="utf-8")

    report = write_back(
        staged,
        ws,
        ["AgentCore/trash/sneak.txt", "AgentCore/规则/ok.md"],
        max_bytes=1024,
        max_files=10,
    )

    assert report.written == ["AgentCore/规则/ok.md"]
    assert report.skipped == ["AgentCore/trash/sneak.txt"]
    assert not (ws / "AgentCore" / "trash").exists()
    assert (ws / "AgentCore" / "规则" / "ok.md").read_text(encoding="utf-8") == "ok"


def test_write_back_containment_blocks_symlinked_parent_escape(tmp_path: Path):
    outside = tmp_path / "outside"
    outside.mkdir()
    ws = tmp_path / "ws"
    ws.mkdir()
    _make_symlink_or_skip(outside, ws / "evil")

    staged = tmp_path / "staged"
    (staged / "evil").mkdir(parents=True)
    (staged / "evil" / "payload.txt").write_text("x", encoding="utf-8")

    report = write_back(
        staged, ws, ["evil/payload.txt"], max_bytes=1024, max_files=10
    )

    assert report.written == []
    assert report.skipped == ["evil/payload.txt"]
    assert not (outside / "payload.txt").exists()


def test_write_back_skips_symlink_source_and_nonfile_dest(tmp_path: Path):
    ws = tmp_path / "ws"
    (ws / "taken").mkdir(parents=True)  # dest exists as a directory
    staged = tmp_path / "staged"
    staged.mkdir()
    (staged / "taken").write_text("clobber?", encoding="utf-8")

    report = write_back(staged, ws, ["taken"], max_bytes=1024, max_files=10)

    assert report.written == []
    assert report.skipped == ["taken"]
    assert (ws / "taken").is_dir()


@pytest.mark.skipif(sys.platform != "linux", reason="sandbox staging perms are Linux-only")
def test_prepare_staging_grants_sandbox_uid_write_and_other_read(tmp_path: Path):
    import stat

    staging = tmp_path / "staged"
    staging.mkdir()
    (staging / "seed.txt").write_text("seed", encoding="utf-8")

    prepare_bind_tree_for_sandbox(staging)

    st_dir = staging.stat()
    st_file = (staging / "seed.txt").stat()
    dir_mode = stat.S_IMODE(st_dir.st_mode)
    file_mode = stat.S_IMODE(st_file.st_mode)

    if os.geteuid() == 0:
        assert st_dir.st_uid == SANDBOX_OCI_UID
        assert st_dir.st_gid == SANDBOX_OCI_GID
        assert st_file.st_uid == SANDBOX_OCI_UID
        assert dir_mode & 0o002 == 0  # not world-writable
        assert dir_mode & 0o020 == 0  # group write only for owner-aligned case
        assert dir_mode & 0o200  # owner write
        assert file_mode & 0o004  # other read for copy-out
    else:
        assert dir_mode & 0o002  # world-writable exchange surface
        assert file_mode & 0o004  # world-readable for copy-out


@pytest.mark.skipif(sys.platform != "linux", reason="sandbox staging perms are Linux-only")
def test_stage_workspace_then_sandbox_write_and_write_back(tmp_path: Path):
    """Simulate uid 65534 write into staging + app-user copy-out."""
    import stat

    ws = tmp_path / "ws"
    ws.mkdir()
    staged = tmp_path / "staged"
    before = stage_workspace(ws, staged, max_bytes=1024 * 1024)

    out_dir = staged / "out"
    out_dir.mkdir(exist_ok=True)
    artifact = out_dir / "from_sandbox.txt"
    try:
        os.chown(out_dir, SANDBOX_OCI_UID, SANDBOX_OCI_GID)
        os.chown(artifact, SANDBOX_OCI_UID, SANDBOX_OCI_GID)
        artifact.write_text("sandbox-bytes", encoding="utf-8")
        os.chmod(artifact, stat.S_IMODE(artifact.stat().st_mode) | 0o004)
    except PermissionError:
        artifact.write_text("sandbox-bytes", encoding="utf-8")
        os.chmod(out_dir, out_dir.stat().st_mode | 0o007)
        os.chmod(artifact, artifact.stat().st_mode | 0o006)

    changes = collect_changes(staged, before)
    report = write_back(staged, ws, changes, max_bytes=1024, max_files=10)

    assert report.written == ["out/from_sandbox.txt"]
    assert (ws / "out" / "from_sandbox.txt").read_text(encoding="utf-8") == "sandbox-bytes"
