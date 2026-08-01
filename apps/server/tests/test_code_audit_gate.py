"""code_audit 结构闸（L2b / L3）单元测试。"""

from agentcore.runtime.runs.code_audit_gate import (
    code_audit_json_failures,
    validate_code_audit_payload,
)
from agentcore.runtime.runs.contract import check_contract
from agentcore.runtime.runs.types import Deliverable


def _ok_finding(**overrides):
    base = {
        "id": "S1",
        "severity": "低",
        "verification": "全文精读",
        "verdict": "属实",
        "evidence": "foo.py:10",
        "summary": "小问题",
    }
    base.update(overrides)
    return base


def test_validate_rejects_unread_as_medium():
    fails = validate_code_audit_payload(
        {
            "schema_version": 1,
            "findings": [
                _ok_finding(
                    severity="中",
                    verification="静态推断·未读全",
                    verdict="属实",
                )
            ],
        }
    )
    assert any("不得标中/高" in f for f in fails)


def test_validate_high_requires_trigger_and_reachability():
    fails = validate_code_audit_payload(
        {
            "findings": [
                _ok_finding(severity="高", category="安全"),
            ]
        }
    )
    assert any("trigger_path" in f for f in fails)
    assert any("reachability" in f for f in fails)


def test_validate_l3_rejects_timeout_as_medium_defect():
    fails = validate_code_audit_payload(
        {
            "findings": [
                _ok_finding(
                    severity="中",
                    summary="desktop typecheck 超时",
                    evidence="tsc --noEmit Timeout: execution exceeded 300s",
                )
            ]
        }
    )
    assert any("超时" in f and "中+" in f for f in fails)


def test_validate_accepts_clean_low_finding():
    assert (
        validate_code_audit_payload({"findings": [_ok_finding()]}) == []
    )


def test_check_contract_code_audit_gate_wires_through():
    md = "## 〇、人审速览\n## 一、属实缺陷\n验证方式\n定案\n## 二、已撤销\n## 三、观察与工程债\n"
    json_path = "AgentCore/文档/reviews/x.audit.json"
    md_path = "AgentCore/文档/reviews/x.md"
    bad_json = '{"findings":[{"severity":"中","verification":"静态推断·未读全","verdict":"属实","evidence":"a:1","summary":"x"}]}'
    d = Deliverable(
        form="files",
        artifacts=[md_path, json_path],
        required_sections=["〇、人审速览", "一、属实缺陷", "二、已撤销", "三、观察与工程债"],
        must_contain=["验证方式", "定案"],
        strict=True,
        code_audit_gate=True,
    )
    verdict = check_contract(
        "简报",
        d,
        files_written=2,
        workspace_paths=[md_path, json_path],
        artifact_contents={md_path: md, json_path: bad_json},
    )
    assert not verdict.ok
    assert any("不得标中/高" in f for f in verdict.failures)


def test_code_audit_json_failures_missing_file():
    fails = code_audit_json_failures(
        artifacts=["AgentCore/文档/reviews/x.audit.json"],
        workspace_paths=[],
        artifact_contents={},
    )
    assert any("缺少" in f for f in fails)
