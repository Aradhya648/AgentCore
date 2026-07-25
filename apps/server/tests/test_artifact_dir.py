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


def test_apply_empty_artifacts_gets_dir_prefix_gate():
    d = Deliverable(form="files")
    apply_artifact_dir_defaults(d, role="研究员", task="讨论白板并写调研笔记")
    assert d.artifact_dir == RESEARCH_DIR
    assert d.artifacts == [f"{RESEARCH_DIR}/"]


def test_describe_mentions_artifact_dir_filename_only():
    d = Deliverable(form="files", artifact_dir=RESEARCH_DIR, artifacts=[f"{RESEARCH_DIR}/"])
    desc = describe_deliverable(d)
    assert f"案卷落盘目录：`{RESEARCH_DIR}/`" in desc
    assert "只定文件名" in desc
    assert "勿写到工作区根" in desc


def test_contract_root_write_fails_under_artifact_dir():
    d = Deliverable(form="files", artifact_dir=RESEARCH_DIR, artifacts=[f"{RESEARCH_DIR}/"])
    root = check_contract(
        "已写",
        d,
        files_written=1,
        workspace_paths=["miro-research.md"],
    )
    assert not root.ok
    assert any("未落盘" in f for f in root.failures)

    ok = check_contract(
        "已写",
        d,
        files_written=1,
        workspace_paths=[f"{RESEARCH_DIR}/miro-research.md"],
    )
    assert ok.ok


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
    assert d.artifacts == [f"{RESEARCH_DIR}/"]
    desc = describe_deliverable(d)
    assert RESEARCH_DIR in desc


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
