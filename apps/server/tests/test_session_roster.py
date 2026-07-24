"""留人 roster 治理 (P2): SessionStore 的 TTL / 条数 / 字节 / LRU 闸，以及
SessionRegistry 的 conversation 维度跨回合留存 + 空闲回收 + 会话数上限。

纯内存单元测试，不触 LLM。通过把 ``updated_at`` / ``last_access`` 拨到过去来确定性地
触发过期，而非真实 sleep。
"""

import time

from agentcore.llm.provider.protocol import LLMMessage
from agentcore.runtime.runs import RunSession, RunSpec
from agentcore.runtime.sessions import (
    SessionRegistry,
    SessionStore,
    default_session_registry,
)


def _session(run_id: str, *, text: str = "x") -> RunSession:
    spec = RunSpec(run_id=run_id, agent_id=run_id, role="A", task="t")
    return RunSession(
        run_id=run_id,
        spec=spec,
        transcript=[LLMMessage(role="assistant", content=text)],
        content=text,
    )


# --- SessionStore：三道闸 ------------------------------------------------------


def test_store_get_evicts_expired_session():
    # 过期 session 在 get 时被剔除 → 命中落空 → 回落甲。
    store = SessionStore(ttl_seconds=10)
    s = _session("r1")
    store.put(s)
    s.updated_at = time.time() - 100  # age past the TTL after insertion
    assert store.get("r1") is None
    assert "r1" not in store


def test_store_lru_evicts_oldest_over_count_cap():
    store = SessionStore(max_sessions=2)
    store.put(_session("a"))
    store.put(_session("b"))
    store.put(_session("c"))  # over cap → evict LRU (a)
    assert "a" not in store
    assert "b" in store
    assert "c" in store
    assert len(store) == 2


def test_store_get_refreshes_lru_recency():
    # 读一次会刷新最近使用，使其在淘汰中存活、把没读过的顶出去。
    store = SessionStore(max_sessions=2)
    store.put(_session("a"))
    store.put(_session("b"))
    assert store.get("a") is not None  # touch a → b becomes the LRU
    store.put(_session("c"))  # evict LRU (b), keep the freshly-read a
    assert "a" in store
    assert "b" not in store
    assert "c" in store


def test_store_evicts_over_byte_cap():
    store = SessionStore(max_bytes=10)
    store.put(_session("a", text="x" * 8))
    store.put(_session("b", text="y" * 8))  # total 16 > 10 → evict LRU (a)
    assert "a" not in store
    assert "b" in store


# --- SessionRegistry：conversation 维度 ---------------------------------------


def test_registry_same_conversation_persists_across_turns():
    # 同一 conversation 跨回合拿到的是【同一个】roster → 下一回合 revise 能命中。
    reg = SessionRegistry()
    turn1 = reg.get_or_create("conv1")
    turn1.put(_session("r1"))
    turn2 = reg.get_or_create("conv1")
    assert turn2 is turn1
    assert "r1" in turn2


def test_registry_isolates_distinct_conversations():
    reg = SessionRegistry()
    assert reg.get_or_create("A") is not reg.get_or_create("B")
    assert len(reg) == 2


def test_registry_lru_evicts_oldest_conversation_over_cap():
    reg = SessionRegistry(max_conversations=2)
    reg.get_or_create("c1")
    reg.get_or_create("c2")
    reg.get_or_create("c3")  # over cap → evict LRU conversation (c1)
    assert "c1" not in reg
    assert "c2" in reg
    assert "c3" in reg


def test_registry_reaps_idle_conversation():
    # 空闲超过 conversation TTL 的会话整盘被清，再访问得到一个全新空 roster → 回落甲。
    reg = SessionRegistry(conversation_ttl_seconds=10)
    store = reg.get_or_create("c1")
    store.put(_session("r1"))
    store.last_access = time.time() - 100  # idle past the TTL
    fresh = reg.get_or_create("c1")
    assert fresh is not store
    assert "r1" not in fresh


def test_default_registry_is_process_singleton():
    assert default_session_registry() is default_session_registry()
