"""通用回放 source 适配器（录制回放通用化提案 步③）。

回放 = 同一 SSE 事件契约的另一种事件源。本包只做「读超集文档 → 按消费端
准备事件流」；挂起 / 恢复 / 正文重灌仍走 runtime 共享实现（红线 §3.3）。

消费端两路互斥（提案 §四）——适配器 API 显式表达，禁止同一会话双注入：

* **A = FOLD** — 前端 fold 直灌（今日 ``#/preview``）；永不重铸交互 id
* **B = SINK** — 服务端 EventSink 注入（今日 demo tape player 收敛至此）；默认重铸

demo tape 保留的应用层修饰（catalog / binding / pacing / 导出剪辑 / 真暂停接线）
仍在 ``demo_tape/``；「读磁带 → 注入前的事件准备」走本包。
"""

from agentcore.replay.consumer import (
    ConsumerKind,
    ReplaySource,
    assert_fold_consumer,
    assert_sink_consumer,
)
from agentcore.replay.document import DocumentKind, EventDocument, open_event_document
from agentcore.replay.prepare import prepare_replay_source

__all__ = [
    "ConsumerKind",
    "DocumentKind",
    "EventDocument",
    "ReplaySource",
    "assert_fold_consumer",
    "assert_sink_consumer",
    "open_event_document",
    "prepare_replay_source",
]
