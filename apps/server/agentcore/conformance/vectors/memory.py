"""Conformance vectors for memory consolidation extraction (Agent记忆与知识系统 §1.5).

Guards the extraction prompt + parse pipeline against regression. Each vector is a
synthetic ``MemoryExtractInput`` paired with a hand-verified golden LLM JSON response
and explicit expectations on parsed ops — unlike the SSE event vectors in sibling
modules, these do NOT feed ``conformance.export`` / protocol fold goldens.

See ``vectors/__init__.py`` for the aggregated ``MEMORY_VECTORS`` registry.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from agentcore.memory.user_memory import (
    MemoryAction,
    MemoryExtractInput,
    _is_cold_start,
    _render_extract_prompt,
    parse_memory_ops,
)

_USER = "u_conformance"
_TODAY = "2026-07-06"


@dataclass(frozen=True)
class MemoryConsolidationVector:
    """One synthetic extraction scenario + golden model output + hand-verified bounds."""

    input: MemoryExtractInput
    golden_raw: str
    expect_min_ops: int = 0
    expect_max_ops: int | None = None
    expect_min_add_ops: int = 0
    require_cold_start_banner: bool = False

    def parsed_ops(self) -> list:
        return parse_memory_ops(self.golden_raw, folder_id=self.input.folder_id)

    def validate(self) -> None:
        """Assert golden parses and meets this vector's hand-verified expectations."""
        ops = self.parsed_ops()
        n = len(ops)
        if n < self.expect_min_ops:
            raise AssertionError(f"expected >= {self.expect_min_ops} ops, got {n}")
        if self.expect_max_ops is not None and n > self.expect_max_ops:
            raise AssertionError(f"expected <= {self.expect_max_ops} ops, got {n}")
        add_count = sum(1 for op in ops if op.action == MemoryAction.ADD)
        if add_count < self.expect_min_add_ops:
            raise AssertionError(f"expected >= {self.expect_min_add_ops} add ops, got {add_count}")
        if self.require_cold_start_banner:
            prompt = _render_extract_prompt(self.input)
            if "# COLD START" not in prompt:
                raise AssertionError("cold-start vector must render the COLD START banner")
            if not _is_cold_start(self.input):
                raise AssertionError("cold-start vector input must be a cold start")


def _memory_cold_start_extraction() -> MemoryConsolidationVector:
    """冷启动提取：偏好与画像均为空，对话含明确用户特征信号 → 必须写入。"""
    golden = (
        '{"ops": ['
        '{"action": "add", "section": "技术栈与工具", "content": "倾向使用 pnpm 管理前端项目"},'
        '{"action": "add", "section": "沟通偏好", "content": "倾向用中文交流"},'
        '{"action": "add", "section": "技术栈与工具", "content": "团队后端使用 PostgreSQL"}'
        "]}"
    )
    return MemoryConsolidationVector(
        input=MemoryExtractInput(
            user_id=_USER,
            current_profile="",
            current_preferences="",
            messages=[
                {"role": "user", "content": "我用 pnpm 管理前端项目，请用中文回复。"},
                {"role": "assistant", "content": "好的，我会用中文回复。需要我帮你做什么？"},
                {"role": "user", "content": "我们团队用 PostgreSQL 做后端数据库。"},
            ],
            today=_TODAY,
        ),
        golden_raw=golden,
        expect_min_ops=1,
        expect_min_add_ops=1,
        require_cold_start_banner=True,
    )


def _memory_ephemeral_task_no_write() -> MemoryConsolidationVector:
    """纯任务对话不写入：记忆已有内容，对话仅为一次性格式化任务 → 空 ops。"""
    return MemoryConsolidationVector(
        input=MemoryExtractInput(
            user_id=_USER,
            current_profile=(
                "## 技术栈与工具\n"
                "- 倾向使用 pnpm 管理前端项目\n"
                "- 团队后端使用 PostgreSQL"
            ),
            current_preferences="## 沟通偏好\n- 倾向用中文交流",
            messages=[
                {
                    "role": "user",
                    "content": '帮我格式化这段 JSON：{"a":1,"b":[2,3]}',
                },
                {
                    "role": "assistant",
                    "content": '{\n  "a": 1,\n  "b": [2, 3]\n}',
                },
            ],
            today=_TODAY,
        ),
        golden_raw='{"ops": []}',
        expect_max_ops=0,
    )


MEMORY_VECTORS: dict[str, tuple[str, Callable[[], MemoryConsolidationVector]]] = {
    "memory_cold_start_extraction": (
        "记忆整合：冷启动提取（空记忆 + 用户特征信号 → 非空 add ops）",
        _memory_cold_start_extraction,
    ),
    "memory_ephemeral_task_no_write": (
        "记忆整合：纯任务对话不写入（已有记忆 + 临时任务 → 空 ops）",
        _memory_ephemeral_task_no_write,
    ),
}


def validate_all_memory_vectors() -> None:
    """Run hand-verified expectations for every registered memory vector."""
    for name, (_description, builder) in MEMORY_VECTORS.items():
        try:
            builder().validate()
        except AssertionError as exc:
            raise AssertionError(f"memory vector {name!r}: {exc}") from exc
