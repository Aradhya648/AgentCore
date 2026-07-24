"""批 D2：案卷台账锚写入 / 开赛预登记 / 无幕1 零行为（零 LLM）。"""

from __future__ import annotations

from pathlib import Path

import pytest

from agentcore.runtime.debate.evidence_ledger import EvidenceLedger
from agentcore.runtime.debate.research_dossier import (
    DOSSIER_SIDE_KEY,
    SYNTHESIZER_FILE,
    dossier_label_from_path,
    ensure_research_file_anchors,
    extract_research_ledger_anchors,
    format_research_dossier_index,
    preregister_research_dossier,
    workspace_has_synthesizer,
)
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace


def test_dossier_label_from_path():
    assert dossier_label_from_path("research/法律透镜报告.md") == "法律"
    assert dossier_label_from_path("research/汇总与命题卡.md") == "汇总"


def test_extract_anchors_from_inline_and_footer():
    body = (
        "一审判赔 500 万#r1。\n\n"
        "## 来源台账锚\n\n"
        "- #r1 · https://court.example/a · 判决书\n"
        "- #r2 · https://news.example/b · 报道\n"
    )
    anchors = extract_research_ledger_anchors(body)
    assert [a.origin_id for a in anchors] == ["#r1", "#r2"]
    assert anchors[0].url == "https://court.example/a"
    assert anchors[0].title == "判决书"


def test_ensure_anchors_keeps_existing():
    body = "事实成立#r3。"
    out = ensure_research_file_anchors(
        body,
        [{"id": "#r1", "url": "https://x.example", "title": "X"}],
    )
    assert out == body


def test_ensure_anchors_appends_footer_when_missing():
    body = "无锚正文。"
    out = ensure_research_file_anchors(
        body,
        [
            {"id": "#r1", "url": "https://a.example", "title": "A"},
            {"id": "#r2", "url": "", "title": "B", "site": "b.example"},
        ],
    )
    assert "## 来源台账锚" in out
    assert "#r1 · https://a.example · A" in out
    assert "#r2" in out
    assert extract_research_ledger_anchors(out)


@pytest.mark.asyncio
async def test_preregister_research_dossier_maps_r_to_e(tmp_path: Path):
    research = tmp_path / "research"
    research.mkdir()
    (research / "法律透镜报告.md").write_text(
        "条款原文#r1。\n\n## 来源台账锚\n\n"
        "- #r1 · https://court.example/x · 合同\n",
        encoding="utf-8",
    )
    (research / "汇总与命题卡.md").write_text("综述无锚。", encoding="utf-8")

    ws = ServerWorkspace(root=tmp_path, sandbox=SubprocessSandbox())
    led = EvidenceLedger()
    idx = await preregister_research_dossier(led, ws)

    assert "【工作区案卷索引·research/】" in idx
    assert "【案卷预登记台账·引用须用下列 #eN】" in idx
    assert "research/法律透镜报告.md" in idx
    assert led.ids  # 至少一条
    legal = next(
        e for e in led.all_entries() if e.get("dossier_path", "").endswith("法律透镜报告.md")
    )
    assert legal["side_key"] == DOSSIER_SIDE_KEY
    assert legal["origin_id"] == "#r1"
    assert legal["dossier_label"] == "法律"
    assert legal["url"] == "https://court.example/x"
    # 无锚汇总文件仍登记整文件一条
    synth = next(
        e for e in led.all_entries() if e.get("dossier_path") == SYNTHESIZER_FILE
    )
    assert synth["origin_id"] == ""
    assert synth["dossier_label"] == "汇总"


@pytest.mark.asyncio
async def test_preregister_no_research_is_noop(tmp_path: Path):
    ws = ServerWorkspace(root=tmp_path, sandbox=SubprocessSandbox())
    led = EvidenceLedger()
    idx = await preregister_research_dossier(led, ws)
    assert idx == ""
    assert led.all_entries() == []


@pytest.mark.asyncio
async def test_workspace_has_synthesizer(tmp_path: Path):
    ws = ServerWorkspace(root=tmp_path, sandbox=SubprocessSandbox())
    assert await workspace_has_synthesizer(ws) is False
    research = tmp_path / "research"
    research.mkdir()
    (research / "汇总与命题卡.md").write_text("x", encoding="utf-8")
    assert await workspace_has_synthesizer(ws) is True


def test_format_index_with_ledger_lines():
    text = format_research_dossier_index(
        ["research/a.md"],
        ledger_lines=["- research/a.md → #e1（幕1 #r1）"],
    )
    assert "案卷预登记台账" in text
    assert "#e1（幕1 #r1）" in text
