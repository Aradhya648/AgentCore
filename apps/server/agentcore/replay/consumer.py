"""消费端判别：A=FOLD / B=SINK，API 层互斥（提案 §四）。"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class ConsumerKind(StrEnum):
    """回放消费端。同一会话只能走一路——全链路 = 走 SINK，前端经真实 SSE 自然消费。"""

    FOLD = "fold"  # A：前端 fold 直灌（#/preview）
    SINK = "sink"  # B：服务端 EventSink 注入（demo tape player）


@dataclass(frozen=True, slots=True)
class ReplaySource:
    """已按单一消费端准备好的事件流。

    ``consumer`` 冻结在构造时：把 FOLD 源灌进 sink、或把 SINK 源直灌 fold，
    须先经 :func:`assert_sink_consumer` / :func:`assert_fold_consumer` —— 双注入
    会在同一会话 fold 两份同一流，适配器 API 显式拒绝。
    """

    consumer: ConsumerKind
    events: tuple[dict[str, Any], ...]
    name: str | None = None
    document_kind: str | None = None
    has_pacing: bool = False


def assert_sink_consumer(source: ReplaySource) -> None:
    """SINK 注入入口门闩：拒绝 FOLD 源（A/B 互斥）。"""
    if source.consumer is not ConsumerKind.SINK:
        raise ValueError(
            f"A/B mutual exclusion: cannot inject consumer={source.consumer.value!r} "
            "into EventSink (FOLD and SINK must not dual-inject the same session)"
        )


def assert_fold_consumer(source: ReplaySource) -> None:
    """FOLD 直灌入口门闩：拒绝 SINK 源（A/B 互斥）。"""
    if source.consumer is not ConsumerKind.FOLD:
        raise ValueError(
            f"A/B mutual exclusion: cannot fold-inject consumer={source.consumer.value!r} "
            "(FOLD and SINK must not dual-inject the same session)"
        )
