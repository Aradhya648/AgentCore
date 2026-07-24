"""Shared constants and helpers for conformance vectors."""

from __future__ import annotations

_CONV = "conv_demo"

_USAGE = {"input": 1200, "output": 300, "reasoning": 120, "cache_hit": 800, "cache_miss": 400}

_COST = {"input": 240_000, "cached": 64_000, "output": 120_000, "total": 360_000, "currency": "USD"}

def _ctx_block(
    channel: str,
    heading: str,
    body: str,
    *,
    source_role: str = "",
    source_run_id: str = "",
    fidelity: str = "",
    truncated: bool = False,
    files: list[str] | None = None,
) -> dict:
    """One wire-shaped ContextBlock for a run_context vector — mirrors the executor's
    ``_context_block_payloads`` output exactly (``chars`` = body length, all keys present)
    so the golden matches what production emits."""
    return {
        "channel": channel,
        "heading": heading,
        "body": body,
        "chars": len(body),
        "truncated": truncated,
        "source_role": source_role,
        "source_run_id": source_run_id,
        "fidelity": fidelity,
        "files": list(files or []),
    }

_ESC_Q = "数据库选 Postgres 还是 MySQL？这关系到后续所有选型，且猜错基本要整段返工。"

_ESC_A = "暂按 Postgres 推进"

