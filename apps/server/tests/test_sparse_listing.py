"""Tests for sparse workspace listing helpers + two-tier ignore rules."""

from pathlib import Path

from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace._paths import (
    AI_NOISE_FILE_SUFFIXES,
    IGNORED_DIRS,
    IGNORED_FILE_SUFFIXES,
    SYSTEM_IGNORED_FILE_SUFFIXES,
    is_ai_noise_file_name,
    is_ignored_dir_name,
    is_ignored_file_name,
    is_ignored_relpath,
    is_internal_zone_relpath,
    is_system_ignored_file_name,
)
from agentcore.workspace.server import ServerWorkspace
from agentcore.workspace.sparse_listing import (
    PROJECT_RECENT_SUPPLEMENT,
    format_remaining_summary,
    is_attachment_path,
    partition_sparse_paths,
)


def test_ignored_dirs_include_git_and_ide_caches_not_bare_internal():
    assert ".agentcore" not in IGNORED_DIRS
    assert "index" not in IGNORED_DIRS
    assert "trash" not in IGNORED_DIRS
    assert "baselines" not in IGNORED_DIRS
    assert ".git" in IGNORED_DIRS
    assert "node_modules" in IGNORED_DIRS
    assert ".turbo" in IGNORED_DIRS
    assert "coverage" in IGNORED_DIRS
    assert ".idea" in IGNORED_DIRS
    assert ".vscode" in IGNORED_DIRS
    assert is_ignored_dir_name(".git")
    assert not is_ignored_dir_name("src")
    assert not is_ignored_dir_name("index")


def test_internal_zone_relpath_is_path_aware():
    assert is_internal_zone_relpath("AgentCore/index")
    assert is_internal_zone_relpath("AgentCore/index/code_search.db")
    assert is_internal_zone_relpath("AgentCore/trash/x")
    assert is_internal_zone_relpath("AgentCore/baselines/m.zip")
    assert not is_internal_zone_relpath("AgentCore")
    assert not is_internal_zone_relpath("AgentCore/规则/x.md")
    assert not is_internal_zone_relpath("AgentCore/记忆/y.md")
    assert not is_internal_zone_relpath("AgentCore/文档/z.md")
    assert not is_internal_zone_relpath("index")
    assert not is_internal_zone_relpath("trash/foo")
    assert not is_internal_zone_relpath("foo/AgentCore/index")


def test_system_suffixes_hide_from_ui_and_ai():
    assert ".db" in SYSTEM_IGNORED_FILE_SUFFIXES
    assert ".sqlite" in SYSTEM_IGNORED_FILE_SUFFIXES
    assert is_system_ignored_file_name("code_search.db")
    assert is_system_ignored_file_name("CODE_SEARCH.DB")
    assert is_system_ignored_file_name("x.pyc")
    assert not is_system_ignored_file_name("photo.png")
    assert not is_system_ignored_file_name("readme.md")


def test_ai_noise_suffixes_are_media_archives_binaries():
    assert ".png" in AI_NOISE_FILE_SUFFIXES
    assert ".zip" in AI_NOISE_FILE_SUFFIXES
    assert ".pack" in AI_NOISE_FILE_SUFFIXES
    assert is_ai_noise_file_name("photo.PNG")
    assert is_ai_noise_file_name("out.zip")
    assert not is_ai_noise_file_name("code_search.db")  # system tier
    assert not is_ai_noise_file_name("report.pdf")  # office docs stay listable


def test_ignored_file_suffixes_combine_both_tiers():
    assert ".db" in IGNORED_FILE_SUFFIXES
    assert ".png" in IGNORED_FILE_SUFFIXES
    assert is_ignored_file_name("code_search.db")
    assert is_ignored_file_name("photo.PNG")
    assert not is_ignored_file_name("readme.md")
    assert not is_ignored_file_name("report.pdf")


def test_ignored_relpath_prunes_nested_noise():
    assert is_ignored_relpath("AgentCore/index/code_search.db")
    assert is_ignored_relpath("node_modules/pkg/index.js")
    assert is_ignored_relpath("src/cache.db")
    assert is_ignored_relpath("out/hero.png")
    assert not is_ignored_relpath("src/app.ts")
    assert not is_ignored_relpath("index/app.ts")  # bare user index/
    assert not is_ignored_relpath("AgentCore/规则/x.md")


def test_partition_bare_lists_all_with_labels():
    rows, remaining = partition_sparse_paths(
        ["attachments/a.txt", "out.md", "data.csv"],
        shared_workspace=False,
    )
    assert remaining == 0
    assert rows == [
        ("attachments/a.txt", "附件"),
        ("out.md", "工作区已有"),
        ("data.csv", "工作区已有"),
    ]


def test_partition_project_keeps_attachments_and_recent_supplement():
    others = [f"f{i}.py" for i in range(PROJECT_RECENT_SUPPLEMENT + 3)]
    rows, remaining = partition_sparse_paths(
        ["attachments/x.md", *others],
        shared_workspace=True,
    )
    assert rows[0] == ("attachments/x.md", "附件")
    assert all(label == "最近触达" for _, label in rows[1:])
    assert len(rows) == 1 + PROJECT_RECENT_SUPPLEMENT
    assert remaining == 3
    assert "file_list" in format_remaining_summary(remaining)


def test_is_attachment_path():
    assert is_attachment_path("attachments/a.txt")
    assert is_attachment_path("attachments")
    assert not is_attachment_path("src/attachments/x.txt")


async def test_index_files_skips_internal_zone_db_and_media(tmp_path: Path):
    (tmp_path / "ok.txt").write_text("x", encoding="utf-8")
    (tmp_path / "hero.png").write_bytes(b"png")
    ac = tmp_path / "AgentCore" / "index"
    ac.mkdir(parents=True)
    (ac / "code_search.db").write_bytes(b"db")
    (tmp_path / "AgentCore" / "规则").mkdir(parents=True)
    (tmp_path / "AgentCore" / "规则" / "x.md").write_text("r", encoding="utf-8")
    (tmp_path / "index").mkdir()
    (tmp_path / "index" / "user.py").write_text("u", encoding="utf-8")
    (tmp_path / "noise.db").write_bytes(b"db")
    git = tmp_path / ".git"
    git.mkdir()
    (git / "config").write_text("g", encoding="utf-8")
    nm = tmp_path / "node_modules" / "dep"
    nm.mkdir(parents=True)
    (nm / "index.js").write_text("x", encoding="utf-8")

    paths, _ = await ServerWorkspace(
        root=tmp_path, sandbox=SubprocessSandbox()
    ).index_files()
    assert paths == ["AgentCore/规则/x.md", "index/user.py", "ok.txt"]


async def test_list_shows_media_hides_system_noise(tmp_path: Path):
    """User UI shares ``list`` — media visible; ``*.db`` / noise dirs hidden."""
    (tmp_path / "ok.txt").write_text("x", encoding="utf-8")
    (tmp_path / "hero.png").write_bytes(b"png")
    (tmp_path / "noise.db").write_bytes(b"db")
    (tmp_path / "AgentCore" / "index").mkdir(parents=True)
    (tmp_path / "AgentCore" / "规则").mkdir(parents=True)
    names = {
        e.path
        for e in await ServerWorkspace(
            root=tmp_path, sandbox=SubprocessSandbox()
        ).list(".", "*")
    }
    assert "ok.txt" in names
    assert "hero.png" in names
    assert "noise.db" not in names
    assert "AgentCore" in names
    ac_names = {
        e.path.rsplit("/", 1)[-1]
        for e in await ServerWorkspace(
            root=tmp_path, sandbox=SubprocessSandbox()
        ).list("AgentCore", "*")
    }
    assert "规则" in ac_names
    assert "index" not in ac_names
