"""Community estimated price table (read-only snapshot in-repo).

Loaded once from ``pricing_data/community_prices.json``. Matching is exact after
lowercase + optional provider-prefix strip — never fuzzy (wrong match is worse
than no match).
"""

from __future__ import annotations

import json
from decimal import Decimal, InvalidOperation
from functools import lru_cache
from pathlib import Path

_DATA_PATH = Path(__file__).resolve().parent / "pricing_data" / "community_prices.json"

_PRICE_KEYS = ("cache_hit", "cache_miss", "output")


def _normalize_keys(model: str) -> list[str]:
    """Exact lookup keys: lowercase full id, then lowercase without first ``prefix/``."""
    key = (model or "").strip().lower()
    if not key:
        return []
    keys = [key]
    if "/" in key:
        _prefix, _, rest = key.partition("/")
        if rest and rest not in keys:
            keys.append(rest)
    return keys


def _card_from_raw(raw: dict) -> dict[str, Decimal] | None:
    try:
        card = {k: Decimal(str(raw[k])) for k in _PRICE_KEYS}
    except (KeyError, InvalidOperation, TypeError):
        return None
    if any(v < 0 for v in card.values()):
        return None
    return card


@lru_cache(maxsize=1)
def _load_index() -> dict[str, dict[str, Decimal]]:
    if not _DATA_PATH.is_file():
        return {}
    try:
        payload = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    models = payload.get("models") if isinstance(payload, dict) else None
    if not isinstance(models, dict):
        return {}
    index: dict[str, dict[str, Decimal]] = {}
    for name, raw in models.items():
        if not isinstance(name, str) or not isinstance(raw, dict):
            continue
        card = _card_from_raw(raw)
        if card is None:
            continue
        for key in _normalize_keys(name):
            index.setdefault(key, card)
    return index


def community_pricing_for(model: str) -> dict[str, Decimal] | None:
    """Exact community card for ``model``, or ``None`` when unknown."""
    index = _load_index()
    for key in _normalize_keys(model):
        card = index.get(key)
        if card is not None:
            return card
    return None


def community_prices_meta() -> dict[str, str]:
    """Snapshot metadata (``as_of`` / ``source``) for diagnostics."""
    if not _DATA_PATH.is_file():
        return {}
    try:
        payload = json.loads(_DATA_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    if not isinstance(payload, dict):
        return {}
    return {
        "as_of": str(payload.get("as_of") or ""),
        "source": str(payload.get("source") or ""),
    }
