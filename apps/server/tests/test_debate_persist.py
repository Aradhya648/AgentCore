"""辩论双产物工作区落盘（机制性写入 ``debate/``）。"""

from __future__ import annotations

from pathlib import Path

from agentcore.runtime.debate import (
    STOP_CONVERGED,
    DebateBrief,
    DebateConfig,
    DebateForm,
    DebateHandoff,
    DebateResult,
    DebateSide,
    JudgeVerdict,
    RoundPolicy,
    RoundResult,
    SideTurn,
)
from agentcore.runtime.debate.persist import (
    artifact_paths,
    artifact_stamp,
    format_artifact_footer,
    persist_debate_artifacts,
    render_brief_file,
    render_narrative_file,
)
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.protocol import WorkspaceIOError
from agentcore.workspace.server import ServerWorkspace


def _sides() -> list[DebateSide]:
    return [
        DebateSide(key="pro", name="正方", stance="支持"),
        DebateSide(key="con", name="反方", stance="反对"),
    ]


def _result(*, motion: str = "该不该做 X") -> DebateResult:
    config = DebateConfig(
        motion=motion,
        form=DebateForm.DEBATE,
        sides=_sides(),
        policy=RoundPolicy.for_form(DebateForm.DEBATE, thorough=False),
    )
    rounds = [
        RoundResult(
            round_no=1,
            focus="成本与收益",
            turns=[
                SideTurn(
                    side_key="pro",
                    side_name="正方",
                    run_id="r1_pro",
                    content="正方发言",
                    ok=True,
                ),
                SideTurn(
                    side_key="con",
                    side_name="反方",
                    run_id="r1_con",
                    content="反方发言",
                    ok=True,
                ),
            ],
            verdict=JudgeVerdict(
                real_clash=True,
                new_arguments=False,
                converged=True,
                rationale="已摊开",
            ),
            summary="双方在成本口径上仍有分歧，但路径已清晰。",
        )
    ]
    brief = DebateBrief(
        crux="做不做 X 的核心权衡",
        strongest_points={"pro": "正方最强论点", "con": "反方最强论点"},
        handoffs=[
            DebateHandoff(kind="value", text="你更看重速度还是稳妥"),
            DebateHandoff(kind="fact", text="X 的成本到底多少"),
        ],
        leaning="基于事实反方略稳",
        confidence="中",
        recommendation="先小步验证再决定",
    )
    return DebateResult(
        config=config, rounds=rounds, brief=brief, stop_reason=STOP_CONVERGED
    )


def test_artifact_stamp_from_moderator_run_id():
    assert artifact_stamp("debate_abcdef12-3456-7890-abcd-ef1234567890") == "abcdef12"
    assert artifact_stamp("debate_") == "场次"
    assert artifact_stamp("") == "场次"


def test_artifact_paths_chinese_under_debate_dir():
    paths = artifact_paths(motion="该不该做 X？", stamp="abcd1234")
    assert paths.brief.startswith("debate/")
    assert paths.narrative.startswith("debate/")
    assert paths.brief.endswith(".md")
    assert "决策简报" in paths.brief
    assert "交锋叙事线" in paths.narrative
    assert "该不该做X" in paths.brief  # 空白压掉
    assert "abcd1234" in paths.brief
    assert paths.brief != paths.narrative


def test_render_files_share_ceo_homologous_content():
    result = _result()
    brief_md = render_brief_file(result)
    narrative_md = render_narrative_file(result)
    assert brief_md.startswith("# 决策简报")
    assert "做不做 X 的核心权衡" in brief_md
    assert "先小步验证再决定" in brief_md
    assert narrative_md.startswith("# 交锋叙事线")
    assert "成本与收益" in narrative_md
    assert "双方在成本口径上仍有分歧" in narrative_md
    assert "幕1 汇总" not in brief_md


def test_render_files_act1_crosslink_header():
    result = _result()
    brief_md = render_brief_file(
        result, act1_summary_path="research/汇总与命题卡.md"
    )
    assert "**幕1 汇总**：`research/汇总与命题卡.md`" in brief_md


async def test_persist_writes_both_files(tmp_path: Path):
    backend = ServerWorkspace(root=tmp_path, sandbox=SubprocessSandbox())
    result = _result()
    paths = await persist_debate_artifacts(backend, result, stamp="a1b2c3d4")
    assert paths is not None
    brief_path = tmp_path / paths.brief
    narrative_path = tmp_path / paths.narrative
    assert brief_path.is_file()
    assert narrative_path.is_file()
    brief_text = brief_path.read_text(encoding="utf-8")
    narrative_text = narrative_path.read_text(encoding="utf-8")
    assert "先小步验证再决定" in brief_text
    assert "成本与收益" in narrative_text
    # 无幕1 汇总 → 文件头不写互链（零行为）
    assert "幕1 汇总" not in brief_text
    assert "幕1 汇总" not in narrative_text
    footer = format_artifact_footer(paths)
    assert paths.brief in footer
    assert paths.narrative in footer


async def test_persist_act1_crosslink_when_synthesizer_exists(tmp_path: Path):
    research = tmp_path / "research"
    research.mkdir()
    (research / "汇总与命题卡.md").write_text("synth", encoding="utf-8")
    backend = ServerWorkspace(root=tmp_path, sandbox=SubprocessSandbox())
    paths = await persist_debate_artifacts(backend, _result(), stamp="a1b2c3d4")
    assert paths is not None
    brief_text = (tmp_path / paths.brief).read_text(encoding="utf-8")
    narrative_text = (tmp_path / paths.narrative).read_text(encoding="utf-8")
    assert "**幕1 汇总**：`research/汇总与命题卡.md`" in brief_text
    assert "**幕1 汇总**：`research/汇总与命题卡.md`" in narrative_text


async def test_persist_multi_debate_does_not_clobber(tmp_path: Path):
    backend = ServerWorkspace(root=tmp_path, sandbox=SubprocessSandbox())
    first = await persist_debate_artifacts(
        backend, _result(motion="该不该做 X"), stamp="11111111"
    )
    second = await persist_debate_artifacts(
        backend, _result(motion="该不该做 X"), stamp="22222222"
    )
    assert first is not None and second is not None
    assert first.brief != second.brief
    assert first.narrative != second.narrative
    assert (tmp_path / first.brief).is_file()
    assert (tmp_path / second.brief).is_file()
    # 同运动词第二场另写，不覆盖第一场
    assert "先小步验证再决定" in (tmp_path / first.brief).read_text(encoding="utf-8")
    assert "先小步验证再决定" in (tmp_path / second.brief).read_text(encoding="utf-8")


async def test_persist_failure_degrades_without_raising(tmp_path: Path):
    class _Boom(ServerWorkspace):
        async def write(self, path: str, content: str) -> int:
            raise WorkspaceIOError("disk full")

    backend = _Boom(root=tmp_path, sandbox=SubprocessSandbox())
    paths = await persist_debate_artifacts(backend, _result(), stamp="deadbeef")
    assert paths is None
    debate_dir = tmp_path / "debate"
    assert not debate_dir.exists() or not any(debate_dir.iterdir())


async def test_persist_narrative_fail_cleans_brief_half_write(tmp_path: Path):
    """brief 成功、narrative 失败 → 清理已写 brief，不留半套文件。"""

    class _NarrativeBoom(ServerWorkspace):
        async def write(self, path: str, content: str) -> int:
            if "交锋叙事线" in path:
                raise WorkspaceIOError("narrative write failed")
            return await super().write(path, content)

    backend = _NarrativeBoom(root=tmp_path, sandbox=SubprocessSandbox())
    paths = await persist_debate_artifacts(backend, _result(), stamp="cafebabe")
    assert paths is None
    debate_dir = tmp_path / "debate"
    assert not debate_dir.exists() or not any(debate_dir.iterdir())
