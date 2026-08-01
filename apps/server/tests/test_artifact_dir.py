"""案卷 ``artifact_dir``：默认填入 + 任务书描述 + 验收前缀闸。"""

from __future__ import annotations

from agentcore.runtime.runs.artifact_dir import (
    apply_artifact_dir_defaults,
    resolve_artifact_dir,
)
from agentcore.runtime.runs.builder import build_run_plan
from agentcore.runtime.runs.contract import check_contract, describe_deliverable
from agentcore.runtime.runs.types import Deliverable
from agentcore.workspace.stage_dirs import RESEARCH_DIR, REVIEWS_DIR


def test_resolve_research_dossier_from_semantic():
    d = Deliverable(form="files", name="竞品笔记")
    assert (
        resolve_artifact_dir(d, role="竞品分析师", task="调研 Miro 并落盘笔记")
        == RESEARCH_DIR
    )


def test_resolve_reviews_from_semantic():
    d = Deliverable(form="files")
    assert (
        resolve_artifact_dir(d, role="审查官", task="审查后端方案并写审查报告")
        == REVIEWS_DIR
    )


def test_resolve_skips_business_artifacts():
    d = Deliverable(form="files", artifacts=["site/index.html"])
    assert resolve_artifact_dir(d, role="前端", task="建站首页") == ""


def test_resolve_derives_from_existing_stage_artifact():
    d = Deliverable(
        form="files",
        artifacts=[f"{RESEARCH_DIR}/法律透镜报告.md"],
    )
    assert resolve_artifact_dir(d, role="法律透镜", task="写报告") == RESEARCH_DIR


def test_apply_fills_dir_prefix_and_relocates_bare_filename():
    d = Deliverable(form="files", artifacts=["miro-research.md"])
    apply_artifact_dir_defaults(d, role="竞品分析师", task="调研 Miro 落盘")
    assert d.artifact_dir == RESEARCH_DIR
    assert d.artifacts == [f"{RESEARCH_DIR}/miro-research.md"]
    assert d.requires_files is True


def test_apply_empty_artifacts_keeps_shared_dir_without_fake_artifact():
    """裸目录只进 artifact_dir（验收），不注入 artifacts 冒充归属键。"""
    d = Deliverable(form="files")
    apply_artifact_dir_defaults(d, role="研究员", task="讨论白板并写调研笔记")
    assert d.artifact_dir == RESEARCH_DIR
    assert d.artifacts == []
    assert d.requires_files is True


def test_describe_mentions_artifact_dir_filename_only():
    d = Deliverable(form="files", artifact_dir=RESEARCH_DIR, artifacts=[])
    desc = describe_deliverable(d)
    assert f"建议案卷落盘目录：`{RESEARCH_DIR}/`" in desc
    assert "只定文件名" in desc
    assert "勿写到工作区根" in desc


def test_contract_root_write_warns_under_artifact_dir():
    d = Deliverable(form="files", artifact_dir=RESEARCH_DIR, requires_files=True, artifacts=[])
    root = check_contract(
        "已写",
        d,
        files_written=1,
        workspace_paths=["miro-research.md"],
    )
    assert root.ok
    assert any("案卷目录" in w for w in root.warnings)

    ok = check_contract(
        "已写",
        d,
        files_written=1,
        workspace_paths=[f"{RESEARCH_DIR}/miro-research.md"],
    )
    assert ok.ok
    assert not any("案卷目录" in w for w in ok.warnings)


def test_artifact_dir_warning_stays_soft_on_delivery_status():
    """Contract artifact_dir path hint → delivery_gaps soft → state=notes."""
    from agentcore.runtime.delegate.delivery_status import build_delivery_status
    from agentcore.runtime.runs.executor_shared import _delivery_gaps_from_warnings
    from agentcore.runtime.runs.file_acceptance import build_file_acceptance
    from agentcore.runtime.runs.plan import RunPlan
    from agentcore.runtime.runs.types import RunPhase, RunSpec, RunState

    d = Deliverable(form="files", artifact_dir=RESEARCH_DIR, requires_files=True, artifacts=[])
    verdict = check_contract(
        "已写",
        d,
        files_written=1,
        workspace_paths=["miro-research.md"],
    )
    assert verdict.ok
    gaps = _delivery_gaps_from_warnings(list(verdict.warnings), None)
    assert any(g.get("severity") == "warning" for g in gaps)
    assert any(g.get("reason") == "path_hint" for g in gaps)

    plan = RunPlan(nodes=[RunSpec(run_id="w1", task="调研 Miro", role="竞品分析师")])
    results = {
        "w1": RunState(
            phase=RunPhase.COMPLETED,
            content="ok",
            files_touched=["miro-research.md"],
            file_acceptance=build_file_acceptance(
                ["miro-research.md"], phase=RunPhase.COMPLETED
            ),
            warnings=list(verdict.warnings),
            delivery_gaps=gaps,
        )
    }
    payload = build_delivery_status(plan, results, execution_id="e-adir-pipe")
    assert payload is not None
    assert payload["state"] == "notes"
    assert all(g.get("severity") == "warning" for g in payload["gaps"])
    assert payload["delivered_files"] == ["miro-research.md"]


def test_build_run_plan_injects_artifact_dir_for_dossier_batch():
    plan, errors = build_run_plan(
        [
            {
                "role": "竞品分析师",
                "task": "调研 Excalidraw 竞品并落盘笔记",
                "deliverable": {"form": "files", "name": "竞品笔记"},
            }
        ]
    )
    assert errors == []
    d = plan.nodes[0].deliverable
    assert d is not None
    assert d.artifact_dir == RESEARCH_DIR
    assert d.artifacts == []
    desc = describe_deliverable(d)
    assert RESEARCH_DIR in desc


def test_shared_artifact_dir_not_sibling_cross():
    """同批只共享案卷目录、无文件级 artifacts → 不触发 sibling 交叉。"""
    from agentcore.runtime.coordination.append_guard import find_sibling_artifact_crosses

    plan, errors = build_run_plan(
        [
            {
                "role": "成本模型研究员",
                "task": "调研 API 定价",
                "deliverable": {"form": "files", "artifact_dir": RESEARCH_DIR},
            },
            {
                "role": "系统架构研究员",
                "task": "调研调度优化",
                "deliverable": {"form": "files", "artifact_dir": RESEARCH_DIR},
            },
        ]
    )
    assert errors == []
    assert all(n.deliverable and n.deliverable.artifacts == [] for n in plan.nodes)
    assert find_sibling_artifact_crosses(plan) == []


def test_same_file_artifact_still_sibling_cross():
    from agentcore.runtime.coordination.append_guard import find_sibling_artifact_crosses

    plan, errors = build_run_plan(
        [
            {
                "role": "前端",
                "task": "写 App",
                "deliverable": {"form": "files", "artifacts": ["src/App.tsx"]},
            },
            {
                "role": "整合",
                "task": "也写 App",
                "deliverable": {"form": "files", "artifacts": ["src/App.tsx"]},
            },
        ]
    )
    assert errors == []
    hits = find_sibling_artifact_crosses(plan)
    assert len(hits) == 1
    assert hits[0].reason == "sibling_artifact"


def test_build_run_plan_leaves_website_artifacts_alone():
    plan, errors = build_run_plan(
        [
            {
                "role": "前端工程师",
                "task": "实现首页",
                "deliverable": {
                    "form": "files",
                    "artifacts": ["site/index.html"],
                },
            }
        ]
    )
    assert errors == []
    d = plan.nodes[0].deliverable
    assert d is not None
    assert d.artifact_dir == ""
    assert d.artifacts == ["site/index.html"]


def test_resolve_ignores_research_path_citation_in_coding_brief():
    """复现：UX/前端 brief 只引用案卷设计文档路径 → 不得绑 RESEARCH_DIR。"""
    d = Deliverable(form="files", artifacts=["src/ui/goalTracker.ts"])
    task = (
        "按 `AgentCore/文档/research/法庭迷局/UX系统设计.md` 实现导航与 goalTracker；"
        "落盘 src/ui/"
    )
    assert resolve_artifact_dir(d, role="UX 系统工程师", task=task) == ""

    empty = Deliverable(form="files")
    assert (
        resolve_artifact_dir(empty, role="前端工程师", task=task) == ""
    )


def test_resolve_path_citation_plus_real_research_intent_still_binds():
    """剥掉路径后仍有「调研」成文意图 → 仍绑案卷。"""
    d = Deliverable(form="files")
    task = f"阅读 `{RESEARCH_DIR}/旧笔记.md` 后继续调研竞品并落盘"
    assert resolve_artifact_dir(d, role="竞品分析师", task=task) == RESEARCH_DIR


def test_resolve_code_verified_skips_semantic_dossier():
    d = Deliverable(form="files")
    assert (
        resolve_artifact_dir(
            d,
            role="修码工程师",
            task="研究现有导航并修好类型错误",
            code_verified=True,
        )
        == ""
    )


def test_resolve_code_verified_keeps_explicit_dossier_artifacts():
    d = Deliverable(
        form="files",
        artifacts=[f"{RESEARCH_DIR}/调研笔记.md"],
    )
    assert (
        resolve_artifact_dir(
            d, role="研究员", task="写调研", code_verified=True
        )
        == RESEARCH_DIR
    )


def test_build_run_plan_coding_brief_with_research_path_no_artifact_dir():
    plan, errors = build_run_plan(
        [
            {
                "role": "UX 系统工程师",
                "task": (
                    "根据 AgentCore/文档/research/法庭迷局/UX系统设计.md "
                    "实现 src/ui 交互系统"
                ),
                "deliverable": {
                    "form": "files",
                    "artifacts": ["src/ui/nav_system.ts"],
                },
            }
        ],
        code_verified=True,
    )
    assert errors == []
    d = plan.nodes[0].deliverable
    assert d is not None
    assert d.artifact_dir == ""
    assert d.artifacts == ["src/ui/nav_system.ts"]
