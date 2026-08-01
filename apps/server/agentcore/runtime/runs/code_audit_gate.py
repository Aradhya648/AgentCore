"""``code_audit`` 报告结构闸（L2b）：校验 ``*.audit.json`` 字段语义。

与成篇审计硬门（``research_report`` 独立审校）正交；与协议 ``ProjectedTurn`` 无关。
由 :class:`~agentcore.runtime.runs.types.Deliverable` 的 ``code_audit_gate`` 盖戳触发，
挂在 :func:`~agentcore.runtime.runs.contract.check_contract`。
"""

from __future__ import annotations

import json
import re
from typing import Any

_VERIFICATIONS = frozenset({"全文精读", "运行验证", "静态推断·未读全", "待核实"})
_VERDICTS = frozenset({"属实", "误报", "部分属实", "待核实"})
_SEVERITIES = frozenset({"高", "中", "低", "观察·工程"})
_SECURITY_CATEGORIES = frozenset({"安全", "路径", "注入"})

# L3：全量 typecheck / pytest 超时不得充当中+缺陷证据。
_TIMEOUT_AS_DEFECT = re.compile(
    r"(typecheck|tsc\b|pytest|test:server:unit).{0,40}(timeout|超时|预算耗尽|exceeded\s+\d+s)"
    r"|(timeout|超时|预算耗尽).{0,40}(typecheck|tsc\b|pytest|全量单测)",
    re.IGNORECASE,
)


def parse_audit_json(text: str) -> tuple[dict[str, Any] | None, str | None]:
    """Return ``(obj, error)``. ``error`` set when unparseable or not an object."""
    raw = text.strip()
    if raw.startswith("```"):
        lines = raw.split("\n")
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        raw = "\n".join(lines).strip()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        return None, f"audit JSON 无法解析：{exc}"
    if not isinstance(data, dict):
        return None, "audit JSON 根须为对象"
    return data, None


def validate_code_audit_payload(data: dict[str, Any]) -> list[str]:
    """Semantic failures for one ``*.audit.json`` object (empty = pass)."""
    failures: list[str] = []
    findings = data.get("findings")
    if not isinstance(findings, list):
        return ["audit JSON 缺少 findings 数组"]

    for i, item in enumerate(findings):
        prefix = f"findings[{i}]"
        if not isinstance(item, dict):
            failures.append(f"{prefix} 须为对象")
            continue
        sev = _as_str(item.get("severity"))
        ver = _as_str(item.get("verification"))
        verd = _as_str(item.get("verdict"))
        evidence = _as_str(item.get("evidence"))
        summary = _as_str(item.get("summary") or item.get("id"))
        category = _as_str(item.get("category"))
        reach = _as_str(item.get("reachability"))
        trigger = _as_str(item.get("trigger_path"))

        if not summary:
            failures.append(f"{prefix} 缺少 summary 或 id")
        if sev not in _SEVERITIES:
            failures.append(f"{prefix} severity 无效（须为 高|中|低|观察·工程）")
        if ver not in _VERIFICATIONS:
            failures.append(f"{prefix} verification 无效")
        if verd not in _VERDICTS:
            failures.append(f"{prefix} verdict 无效")
        if not evidence:
            failures.append(f"{prefix} 缺少 evidence")

        # 未读全 / 待核实 → 不得中+
        if (ver == "静态推断·未读全" or verd == "待核实") and sev in {"高", "中"}:
            failures.append(
                f"{prefix} 验证方式未读全或定案待核实时不得标中/高（现 severity={sev}）"
            )

        # 高必须有触发路径
        if sev == "高" and not trigger:
            failures.append(f"{prefix} severity=高 须写 trigger_path")

        # 可达性：安全/路径/注入 或 高
        need_reach = sev == "高" or category in _SECURITY_CATEGORIES
        if need_reach and not reach:
            failures.append(
                f"{prefix} 安全/路径/注入类或 severity=高 须写 reachability"
            )

        # L3：超时充中+
        if sev in {"高", "中"}:
            blob = f"{summary}\n{evidence}\n{_as_str(item.get('detail'))}"
            if _TIMEOUT_AS_DEFECT.search(blob):
                failures.append(
                    f"{prefix} 禁止把全量 typecheck/pytest 超时当作中+缺陷证据"
                    "（应标观察·工程）"
                )

    return failures


def code_audit_json_failures(
    *,
    artifacts: list[str],
    workspace_paths: list[str],
    artifact_contents: dict[str, str] | None,
) -> list[str]:
    """Locate ``*.audit.json`` among declared artifacts / contents and validate."""
    if artifact_contents is None:
        return ["code_audit 结构闸需要读取 audit JSON 文件内容"]

    declared = [
        p.replace("\\", "/").strip()
        for p in artifacts
        if isinstance(p, str) and p.replace("\\", "/").endswith(".audit.json")
    ]

    candidates: list[str] = []
    for pat in declared:
        matched_key: str | None = None
        for key in artifact_contents:
            nk = key.replace("\\", "/").strip()
            if nk == pat or nk.endswith("/" + pat) or nk.endswith(pat):
                matched_key = key
                break
        if matched_key is not None:
            candidates.append(matched_key)
            continue
        if any(
            p.replace("\\", "/").strip() == pat or p.replace("\\", "/").endswith("/" + pat)
            for p in workspace_paths
        ):
            return [f"无法读取 audit JSON：`{pat}`"]
        return [f"缺少 audit JSON 产物：`{pat}`"]

    if not candidates:
        candidates = [
            k for k in artifact_contents if k.replace("\\", "/").endswith(".audit.json")
        ]
    if not candidates and declared:
        return [f"缺少 audit JSON 产物：`{declared[0]}`"]
    if not candidates:
        return ["code_audit 结构闸未找到 *.audit.json 内容"]

    failures: list[str] = []
    seen: set[str] = set()
    for key in candidates:
        nk = key.replace("\\", "/")
        if nk in seen:
            continue
        seen.add(nk)
        data, err = parse_audit_json(artifact_contents[key])
        if err:
            failures.append(f"`{nk}` {err}")
            continue
        assert data is not None
        failures.extend(validate_code_audit_payload(data))
    return failures


def _as_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


__all__ = [
    "code_audit_json_failures",
    "parse_audit_json",
    "validate_code_audit_payload",
]
