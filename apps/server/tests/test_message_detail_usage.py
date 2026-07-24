"""MessageDetail's reload projection of the row usage snapshot (Tier 2 重载持久化).

The assistant row's ``usage`` column stores a long-key token snapshot
(``{input_tokens, …, rounds}``) written by ``_persist_turn_result``. ``MessageDetail``
surfaces it on reload: the ``usage`` field is projected to the ledger short-key
``UsageBreakdown`` the client reads, and tokens show only when the turn reported real
spend — a no-spend / errored turn stored zeros, which the live bubble also omits. The
``rounds`` field shares the column but is set by the read route (no own attribute), so
it is not exercised here.
"""

from datetime import UTC, datetime

from agentcore.api.schemas.messages import MessageDetail


def _row(usage: dict | None) -> dict:
    return {
        "id": "m1",
        "conversation_id": "c1",
        "role": "assistant",
        "content": "hi",
        "created_at": datetime.now(UTC),
        "usage": usage,
    }


def test_usage_row_projects_to_short_keys():
    d = MessageDetail.model_validate(
        _row(
            {
                "input_tokens": 100,
                "output_tokens": 40,
                "reasoning_tokens": 12,
                "cache_hit_tokens": 30,
                "cache_miss_tokens": 70,
                "rounds": 3,
            }
        )
    )
    assert d.usage is not None
    assert (d.usage.input, d.usage.output, d.usage.reasoning) == (100, 40, 12)
    assert (d.usage.cache_hit, d.usage.cache_miss) == (30, 70)


def test_no_spend_turn_omits_usage():
    # 报错/空回合 stored zeros → no token meta on reload, parity with the live bubble.
    d = MessageDetail.model_validate(
        _row(
            {
                "input_tokens": 0,
                "output_tokens": 0,
                "reasoning_tokens": 0,
                "cache_hit_tokens": 0,
                "cache_miss_tokens": 0,
                "rounds": 0,
            }
        )
    )
    assert d.usage is None


def test_missing_usage_column_omits_usage():
    # User rows / pre-feature rows carry no usage snapshot.
    d = MessageDetail.model_validate(_row(None))
    assert d.usage is None


def test_inflight_partial_message_detail_shape():
    """流中刷新形状契约 (P0): running + partial content/reasoning is a valid MessageDetail.

    Overlay that *fills* those fields from turn_stream_state is P1; this nails the
    wire shape clients must accept on reload of an in-flight turn.
    """
    d = MessageDetail.model_validate(
        {
            "id": "m-inflight",
            "conversation_id": "c1",
            "role": "assistant",
            "content": "正在生成的半截正",
            "reasoning_content": "先想一步…",
            "status": "running",
            "created_at": datetime.now(UTC),
            "usage": None,
        }
    )
    assert d.status == "running"
    assert d.paused is None
    assert d.content and d.content.startswith("正在生成")
    assert d.reasoning_content and "想" in d.reasoning_content
    assert d.usage is None  # mid-stream often has no token snapshot yet


def test_paused_latch_projects_on_message_detail():
    """Cold-path pause latch (挂起即收口): status=running + paused=true is valid wire.

    Write side keeps ``status=running`` (overlay/promotion latch); read lifts ``paused``
    so clients do not hydrate as streaming. Tokens may be present or absent.
    """
    d = MessageDetail.model_validate(
        {
            "id": "m-paused",
            "conversation_id": "c1",
            "role": "assistant",
            "content": "检查点前已生成的正文",
            "status": "running",
            "paused": True,
            "created_at": datetime.now(UTC),
            "usage": None,
        }
    )
    assert d.status == "running"
    assert d.paused is True
    assert d.content and "检查点" in d.content


def test_inflight_fixture_validates_against_message_detail():
    """Committed rest fixture stays aligned with MessageDetail (contracts gate)."""
    import json
    from pathlib import Path

    fixture_path = (
        Path(__file__).resolve().parents[3]
        / "packages"
        / "protocol-conformance"
        / "fixtures"
        / "rest"
        / "message-detail-inflight-partial.json"
    )
    payload = json.loads(fixture_path.read_text(encoding="utf-8"))
    d = MessageDetail.model_validate(payload["response"])
    assert d.status == "running"
    assert d.content
    assert d.reasoning_content
