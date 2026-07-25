"""辩论消费幕1 research/ 案卷：索引格式 / 工作区探测（零 LLM）。"""

from __future__ import annotations

import pytest

from agentcore.runtime.debate.research_dossier import (
    RESEARCH_DIR,
    format_research_dossier_index,
    list_research_artifact_paths,
    workspace_has_research_artifacts,
)
from agentcore.workspace.protocol import DirEntry, PathNotFound


class _FakeBackend:
    def __init__(self, entries: list[DirEntry] | None = None, *, exc: Exception | None = None):
        self._entries = entries or []
        self._exc = exc

    async def list(self, directory: str, pattern: str) -> list[DirEntry]:
        assert directory == RESEARCH_DIR
        if self._exc is not None:
            raise self._exc
        return list(self._entries)


@pytest.mark.asyncio
async def test_list_research_artifact_paths_files_only():
    backend = _FakeBackend(
        [
            DirEntry(path="AgentCore/文档/research/法律透镜报告.md", is_dir=False),
            DirEntry(path="AgentCore/文档/research/子目录", is_dir=True),
            DirEntry(path="AgentCore/文档/research/汇总与命题卡.md", is_dir=False),
        ]
    )
    paths = await list_research_artifact_paths(backend)  # type: ignore[arg-type]
    assert set(paths) == {"AgentCore/文档/research/法律透镜报告.md", "AgentCore/文档/research/汇总与命题卡.md"}
    assert await workspace_has_research_artifacts(backend) is True  # type: ignore[arg-type]


@pytest.mark.asyncio
async def test_list_research_missing_dir_is_empty():
    backend = _FakeBackend(exc=PathNotFound("research"))
    assert await list_research_artifact_paths(backend) == []  # type: ignore[arg-type]
    assert await workspace_has_research_artifacts(backend) is False  # type: ignore[arg-type]


def test_format_research_dossier_index_shape():
    assert format_research_dossier_index([]) == ""
    text = format_research_dossier_index(["AgentCore/文档/research/a.md", "AgentCore/文档/research/b.md"])
    assert text.startswith("【工作区案卷索引·AgentCore/文档/research/】")
    assert "非全文" in text
    assert "file_read" in text
    assert "选读" in text or "勿无差别" in text
    assert "- AgentCore/文档/research/a.md" in text
    assert "- AgentCore/文档/research/b.md" in text


def test_format_research_dossier_index_file_hints():
    from agentcore.runtime.debate.research_dossier import dossier_file_hint

    hint = dossier_file_hint("AgentCore/文档/research/法律透镜报告.md", "# 法律要点\n\n正文……")
    assert "法律" in hint
    assert "字" in hint
    text = format_research_dossier_index(
        ["AgentCore/文档/research/法律透镜报告.md"],
        file_hints={"AgentCore/文档/research/法律透镜报告.md": hint},
    )
    assert "法律透镜报告.md（" in text
    assert "法律要点" in text


@pytest.mark.asyncio
async def test_server_workspace_research_listing(tmp_path):
    """真实 ServerWorkspace：research/ 落盘文件可被探测并格式化为索引。"""
    from agentcore.tools.sandbox.subprocess import SubprocessSandbox
    from agentcore.workspace.server import ServerWorkspace

    research = tmp_path / "AgentCore" / "文档" / "research"
    research.mkdir(parents=True)
    (research / "法律透镜报告.md").write_text("lens", encoding="utf-8")
    (research / "汇总与命题卡.md").write_text("synth", encoding="utf-8")

    ws = ServerWorkspace(root=tmp_path, sandbox=SubprocessSandbox())
    paths = await list_research_artifact_paths(ws)
    assert any(p.endswith("法律透镜报告.md") for p in paths)
    assert any("汇总与命题卡.md" in p for p in paths)
    idx = format_research_dossier_index(paths)
    assert "【工作区案卷索引·AgentCore/文档/research/】" in idx
    assert await workspace_has_research_artifacts(ws) is True
