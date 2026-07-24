"""Sidecar IPC wire-shape constants.

Single source: ``packages/contract-types/src/sidecar-ipc.json``.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[5]
_CONTRACT_PATH = _REPO_ROOT / "packages" / "contract-types" / "src" / "sidecar-ipc.json"


@lru_cache(maxsize=1)
def load_sidecar_ipc_contract() -> dict[str, Any]:
    return json.loads(_CONTRACT_PATH.read_text(encoding="utf-8"))


def turn_result_keys() -> tuple[str, ...]:
    return tuple(load_sidecar_ipc_contract()["turnResult"]["keys"])


def turn_result_usage_keys() -> tuple[str, ...]:
    return tuple(load_sidecar_ipc_contract()["turnResult"]["usageKeys"])


def resume_rpc_param_keys() -> tuple[str, ...]:
    return tuple(load_sidecar_ipc_contract()["resumeRpcParams"]["keys"])


def resume_rpc_required_keys() -> tuple[str, ...]:
    return tuple(load_sidecar_ipc_contract()["resumeRpcParams"]["required"])
