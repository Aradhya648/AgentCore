"""计费归因头的传输契约（billing/attribution.py）。

Persona 是 CEO 自拟的人设标签（「调研员」「前端工程师」…），几乎必然是非 ASCII——
HTTP 头只能走 ASCII（httpx 直接抛 UnicodeEncodeError），所以出站侧百分号编码、
代理入站侧对称解码。本文件钉住这条往返链路：编码后的头必须能构造真实 httpx 请求
（即 ASCII 安全），解码后必须逐字还原；ASCII 旧值原样通过。
"""

from __future__ import annotations

import httpx

from agentcore.billing.attribution import (
    attribution_headers_from_context,
    parse_attribution_headers,
)
from agentcore.core.log_context import log_context
from agentcore.llm.credentials import INFERENCE_PERSONA_HEADER


def test_chinese_persona_roundtrips_through_http_headers():
    """非 ASCII persona：出站编码 → 可上 HTTP 线 → 入站解码逐字还原。"""
    with log_context(run_id="del_1", agent_id="del_1", cost_role="member", persona="调研员"):
        headers = attribution_headers_from_context()

    # The wire value must be ASCII — otherwise httpx refuses the request outright
    # (this was the crash: every persona-attributed sidecar LLM call died here).
    request = httpx.Request("POST", "http://proxy/v1/chat/completions", headers=headers)
    assert request.headers[INFERENCE_PERSONA_HEADER].isascii()

    parsed = parse_attribution_headers(request.headers)
    assert parsed["persona"] == "调研员"
    assert parsed["run_id"] == "del_1"
    assert parsed["role"] == "member"
    assert parsed["call_id"] is not None


def test_ascii_persona_passes_through_unchanged():
    """ASCII 值（CEO / 未编码旧客户端）编码是恒等变换，解码同样原样通过。"""
    with log_context(cost_role="captain", persona="CEO"):
        headers = attribution_headers_from_context()
    assert headers[INFERENCE_PERSONA_HEADER] == "CEO"
    assert parse_attribution_headers(headers)["persona"] == "CEO"


def test_absent_persona_stays_absent():
    with log_context(cost_role="captain"):
        headers = attribution_headers_from_context()
    assert INFERENCE_PERSONA_HEADER not in headers
    assert parse_attribution_headers(headers)["persona"] is None
