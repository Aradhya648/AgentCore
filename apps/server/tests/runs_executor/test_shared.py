from agentcore.runtime.runs.cutoff import (
    DEGRADED_HANDOFF_WARNING,
    REASON_DEGRADED_HANDOFF,
)
from agentcore.runtime.runs.executor_shared import (
    _hard_gap_blocks_completion,
    _is_hard_failure,
)
from agentcore.runtime.runs.types import Deliverable


def test_is_hard_failure_empty_always_hard():
    assert _is_hard_failure("   ", None) is True
    assert _is_hard_failure("", Deliverable(strict=False)) is True


def test_is_hard_failure_nonempty_depends_on_strict():
    assert _is_hard_failure("x", None) is False
    assert _is_hard_failure("x", Deliverable(strict=False)) is False
    assert _is_hard_failure("x", Deliverable(strict=True)) is True


def test_is_hard_failure_requires_files_zero_disk_always_hard():
    """交付真相：requires_files ∧ files_touched==0 不得 soft-complete。"""
    d = Deliverable(requires_files=True, strict=False)
    assert _is_hard_failure("有正文但未落盘", d, files_touched=0) is True
    assert _is_hard_failure("有正文且已落盘", d, files_touched=1) is False


def test_hard_gap_blocks_completion_non_strict_allows():
    """Non-strict (legacy soft-accept) still allows COMPLETED with degraded gaps."""
    gaps = [{"description": DEGRADED_HANDOFF_WARNING, "reason": REASON_DEGRADED_HANDOFF}]
    assert (
        _hard_gap_blocks_completion(gaps, {"degraded": True}, Deliverable(strict=False))
        is None
    )
    assert _hard_gap_blocks_completion(gaps, {"degraded": True}, None) is None


def test_hard_gap_blocks_completion_strict_degraded_no_files():
    """刀1：strict + degraded_handoff + 无落盘 → 仍硬拦。"""
    gaps = [{"description": DEGRADED_HANDOFF_WARNING, "reason": REASON_DEGRADED_HANDOFF}]
    reason = _hard_gap_blocks_completion(
        gaps,
        {"summary": "薄", "degraded": True},
        Deliverable(strict=True, form="files"),
        files_touched=0,
    )
    assert reason is not None
    assert "交接说明不完整" in reason or "不得冒充完成" in reason
    assert "continue_from_run_id" not in reason
    assert "degraded_handoff" not in reason


def test_hard_gap_blocks_completion_strict_degraded_with_files_allows():
    """刀1 / 方案 A：strict + degraded_handoff + 已落盘 → 不 FAILED，放行 COMPLETED。"""
    gaps = [
        {
            "description": DEGRADED_HANDOFF_WARNING,
            "reason": REASON_DEGRADED_HANDOFF,
            "severity": "warning",
        }
    ]
    assert (
        _hard_gap_blocks_completion(
            gaps,
            {"summary": "薄", "degraded": True},
            Deliverable(strict=True, form="files"),
            files_touched=1,
        )
        is None
    )
    # 即便未预盖 severity，有落盘也不硬拦。
    gaps_raw = [
        {"description": DEGRADED_HANDOFF_WARNING, "reason": REASON_DEGRADED_HANDOFF}
    ]
    assert (
        _hard_gap_blocks_completion(
            gaps_raw,
            {"summary": "薄", "degraded": True},
            Deliverable(strict=True, form="files"),
            files_touched=2,
        )
        is None
    )


def test_hard_gap_blocks_completion_strict_missing_artifact_desc():
    gaps = [{"description": "声明的交付物路径未落盘：site/sections/s0.html"}]
    reason = _hard_gap_blocks_completion(gaps, None, Deliverable(strict=True))
    assert reason is not None
    assert "未落盘" in reason or "不得冒充完成" in reason


def test_hard_gap_blocks_completion_soft_warning_alone_ok():
    """Anti-slop soft warnings alone must not trip hard-gap fail."""
    gaps = [{"description": "anti-slop：渐变过多"}]
    assert (
        _hard_gap_blocks_completion(gaps, None, Deliverable(strict=True, form="files"))
        is None
    )
