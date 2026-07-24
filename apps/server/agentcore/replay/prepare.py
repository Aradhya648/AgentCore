"""按消费端准备 ReplaySource（remint / legacy 例外集中于此）。"""

from __future__ import annotations

from typing import Any

from agentcore.demo_tape.identity import remint_interaction_ids
from agentcore.replay.consumer import ConsumerKind, ReplaySource
from agentcore.replay.document import EventDocument, open_event_document
from agentcore.replay.legacy import apply_legacy_captain_tool_run_id_strip


def prepare_replay_source(
    document: EventDocument | dict[str, Any],
    *,
    consumer: ConsumerKind,
    message_id: str | None = None,
) -> ReplaySource:
    """把超集文档准备成**单一**消费端可用的 :class:`ReplaySource`。

    策略（提案 §六 问题 6 / 9 实现期拍板）：

    * **FOLD (A)** — 永不重铸交互 id（巡检 golden / 深链依赖稳定 id）
    * **SINK (B)** — 默认 ``remint_interaction_ids``；并集中应用旧磁带 captain
      ``run_id`` 剥离 legacy 例外（见 :mod:`agentcore.replay.legacy`）

    pacing（``t_ms``）原样保留在事件上——FOLD 消费端忽略等步；SINK 侧由
    demo_tape pacing 修饰层消费。不在此包实现注入 / 挂起语义。
    """
    doc = (
        document
        if isinstance(document, EventDocument)
        else open_event_document(document)
    )
    events: list[dict[str, Any]] = list(doc.events)

    if consumer is ConsumerKind.SINK:
        if not message_id:
            raise ValueError(
                "SINK consumer requires message_id for per-replay identity remint"
            )
        events = remint_interaction_ids(events, message_id=message_id)
        # Legacy exception — stock v1 tapes only; retire with those tapes.
        events = apply_legacy_captain_tool_run_id_strip(events)
    # FOLD: identity stable; no captain-strip (vectors already contract-correct;
    # tape-shaped fold preview treats recorded ids as golden for eyeball parity).

    return ReplaySource(
        consumer=consumer,
        events=tuple(events),
        name=doc.name,
        document_kind=doc.kind.value,
        has_pacing=doc.has_pacing,
    )
