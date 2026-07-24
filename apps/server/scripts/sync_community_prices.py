#!/usr/bin/env python3
"""Sync ``community_prices.json`` from LiteLLM's public model price table.

Manual / offline-friendly: tries to fetch
``model_prices_and_context_window.json`` from the LiteLLM GitHub raw URL; on
network failure keeps / regenerates from the in-repo snapshot metadata only.

Usage (from apps/server)::

    python scripts/sync_community_prices.py
"""

from __future__ import annotations

import json
import sys
import urllib.request
from datetime import date
from decimal import Decimal
from pathlib import Path

_LITELLM_URL = (
    "https://raw.githubusercontent.com/BerriAI/litellm/main/"
    "model_prices_and_context_window.json"
)

_OUT = (
    Path(__file__).resolve().parents[1]
    / "agentcore"
    / "llm"
    / "pricing_data"
    / "community_prices.json"
)

# Keep the curated chat-model set small and explicit (exact ids after lowercase /
# provider-prefix strip). Fuzzy matching is forbidden at runtime.
_ALLOW = {
    "gpt-4o",
    "gpt-4o-mini",
    "gpt-4.1",
    "gpt-4.1-mini",
    "gpt-4.1-nano",
    "o3",
    "o3-mini",
    "o4-mini",
    "claude-sonnet-4-20250514",
    "claude-sonnet-4-5-20250929",
    "claude-opus-4-20250514",
    "claude-3-5-haiku-20241022",
    "claude-3-5-sonnet-20241022",
    "claude-haiku-4-5-20251001",
    "deepseek-v4-flash",
    "deepseek-v4-pro",
    "deepseek-v3",
    "qwen-plus",
    "qwen-turbo",
    "qwen-max",
    "qwen-vl-max",
    "qwen3-235b-a22b",
    "moonshot-v1-8k",
    "moonshot-v1-32k",
    "moonshot-v1-128k",
    "kimi-k2-0711-preview",
    "glm-4-flash",
    "glm-4-plus",
    "glm-4-air",
    "glm-4.5",
    "doubao-seed-2-1-turbo-260628",
    "doubao-pro-32k",
    "doubao-lite-32k",
    "gemini-2.0-flash",
    "gemini-2.5-flash",
    "gemini-2.5-pro",
    "mistral-small-latest",
    "mistral-large-latest",
    "mistral-medium-latest",
    "codestral-latest",
    "llama-3.3-70b",
    "grok-3",
    "grok-3-mini",
}


def _per_million(per_token: object) -> str | None:
    try:
        d = Decimal(str(per_token)) * Decimal("1000000")
    except Exception:
        return None
    if d < 0:
        return None
    text = format(d, "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _strip_prefix(name: str) -> str:
    key = name.strip().lower()
    if "/" in key:
        _p, _, rest = key.partition("/")
        return rest or key
    return key


def _fetch() -> dict | None:
    try:
        with urllib.request.urlopen(_LITELLM_URL, timeout=30) as resp:  # noqa: S310
            return json.loads(resp.read().decode("utf-8"))
    except Exception as exc:  # noqa: BLE001
        print(f"fetch failed: {exc}", file=sys.stderr)
        return None


def main() -> int:
    existing: dict = {}
    if _OUT.is_file():
        existing = json.loads(_OUT.read_text(encoding="utf-8"))

    remote = _fetch()
    models: dict[str, dict[str, str]] = dict(existing.get("models") or {})
    source = existing.get("source") or "manual snapshot"
    if remote is not None:
        source = f"LiteLLM model_prices_and_context_window.json @ {date.today().isoformat()}"
        for raw_name, meta in remote.items():
            if not isinstance(meta, dict):
                continue
            key = _strip_prefix(str(raw_name))
            if key not in _ALLOW:
                continue
            miss = _per_million(meta.get("input_cost_per_token"))
            out = _per_million(meta.get("output_cost_per_token"))
            hit = _per_million(
                meta.get("cache_read_input_token_cost")
                or meta.get("input_cost_per_cached_token")
            )
            if miss is None or out is None:
                continue
            if hit is None:
                # No cache tier published — mirror miss (same posture as curated 豆包).
                hit = miss
            models[key] = {
                "cache_hit": hit,
                "cache_miss": miss,
                "output": out,
            }

    # Keep allow-list order stable; drop unknowns not in allow.
    ordered = {k: models[k] for k in sorted(_ALLOW) if k in models}
    payload = {
        "as_of": date.today().isoformat(),
        "source": source,
        "models": ordered,
    }
    _OUT.parent.mkdir(parents=True, exist_ok=True)
    _OUT.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"wrote {len(ordered)} models → {_OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
