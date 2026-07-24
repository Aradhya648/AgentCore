"""Conversation → tape binding (dev-only, file-backed)."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from agentcore.config import settings
from agentcore.config.paths import PROJECT_ROOT
from agentcore.core.logging import get_logger

logger = get_logger(__name__)


@dataclass(frozen=True)
class TapeBinding:
    conversation_id: str
    tape_path: Path
    speed: float
    max_gap_ms: int
    # Which act to play on the next divert (0-based). Advanced after END_TURN;
    # cleared with the binding after the last act. Reset to 0 on prepare/start.
    turn_index: int = 0


def bindings_path() -> Path:
    raw = (settings.demo_tape_bindings_path or "").strip()
    if raw:
        p = Path(raw)
        return p if p.is_absolute() else PROJECT_ROOT / p
    return PROJECT_ROOT / "demos" / "bindings.json"


def resolve_tape_path(spec: str) -> Path:
    p = Path(spec)
    if p.is_absolute():
        return p
    # Prefer repo-relative; also allow apps/server-relative for convenience.
    cand = PROJECT_ROOT / p
    if cand.exists():
        return cand
    return Path.cwd() / p


def _parse_entry(conversation_id: str, raw: Any) -> TapeBinding | None:
    if isinstance(raw, str):
        return TapeBinding(
            conversation_id=conversation_id,
            tape_path=resolve_tape_path(raw),
            speed=float(settings.demo_tape_speed),
            max_gap_ms=int(settings.demo_tape_max_gap_ms),
            turn_index=0,
        )
    if not isinstance(raw, dict):
        return None
    tape = raw.get("tape") or raw.get("path")
    if not tape:
        return None
    speed = float(raw.get("speed", settings.demo_tape_speed))
    max_gap_ms = int(raw.get("max_gap_ms", settings.demo_tape_max_gap_ms))
    turn_index = int(raw.get("turn_index") or 0)
    if turn_index < 0:
        turn_index = 0
    return TapeBinding(
        conversation_id=conversation_id,
        tape_path=resolve_tape_path(str(tape)),
        speed=speed,
        max_gap_ms=max_gap_ms,
        turn_index=turn_index,
    )


def load_bindings() -> dict[str, TapeBinding]:
    path = bindings_path()
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        logger.warning("demo_tape.bindings_read_failed", path=str(path), error=str(e))
        return {}
    if not isinstance(data, dict):
        return {}
    out: dict[str, TapeBinding] = {}
    for cid, raw in data.items():
        if cid.startswith("_"):
            continue
        binding = _parse_entry(str(cid), raw)
        if binding is not None:
            out[str(cid)] = binding
    return out


def peek_binding(conversation_id: str) -> TapeBinding | None:
    """Look up a binding without requiring ``DEMO_TAPE_REPLAY_ENABLED``.

    Use for diagnostics (e.g. sidecar detecting a misbound local session).
    Playback diversion still goes through :func:`resolve_binding`.
    """
    return load_bindings().get(conversation_id)


def resolve_binding(conversation_id: str) -> TapeBinding | None:
    if not settings.demo_tape_replay_enabled:
        return None
    return load_bindings().get(conversation_id)


# User-facing copy when a tape-bound conversation is routed to the desktop sidecar
# (server binding is invisible there → silent "normal AI" without this check).
LOCAL_SESSION_BOUND_MSG = (
    "演示磁带已绑定到本会话，但回合走了 sidecar 本地引擎，服务端回放不会生效"
    "（会变成普通 AI 回复）。请改用云端会话：命令面板「演示回放」或「云端随手聊」。"
)


def _read_bindings_file() -> dict[str, Any]:
    path = bindings_path()
    if not path.exists():
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
        return loaded if isinstance(loaded, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _write_bindings_file(data: dict[str, Any]) -> Path:
    path = bindings_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path


def write_binding(
    conversation_id: str,
    *,
    tape: str,
    speed: float | None = None,
    max_gap_ms: int | None = None,
) -> Path:
    """Upsert one conversation binding into the bindings file.

    Always resets ``turn_index`` to 0 (prepare / start / re-bind).
    """
    data = _read_bindings_file()
    entry: dict[str, Any] = {"tape": tape, "turn_index": 0}
    if speed is not None:
        entry["speed"] = speed
    if max_gap_ms is not None:
        entry["max_gap_ms"] = max_gap_ms
    data[conversation_id] = entry
    path = _write_bindings_file(data)
    logger.info(
        "demo_tape.binding_written",
        conversation_id=conversation_id,
        tape=tape,
        speed=speed,
        max_gap_ms=max_gap_ms,
        turn_index=0,
        path=str(path),
    )
    return path


def clear_binding(conversation_id: str) -> bool:
    """Remove a conversation binding. Returns True when an entry was deleted."""
    data = _read_bindings_file()
    if conversation_id not in data:
        return False
    del data[conversation_id]
    path = _write_bindings_file(data)
    logger.info(
        "demo_tape.binding_cleared",
        conversation_id=conversation_id,
        path=str(path),
    )
    return True


def set_binding_turn_index(conversation_id: str, turn_index: int) -> TapeBinding | None:
    """Persist the act cursor for an existing binding. Returns the updated binding."""
    data = _read_bindings_file()
    raw = data.get(conversation_id)
    if raw is None:
        return None
    if isinstance(raw, str):
        entry: dict[str, Any] = {"tape": raw, "turn_index": max(0, int(turn_index))}
    elif isinstance(raw, dict):
        entry = dict(raw)
        entry["turn_index"] = max(0, int(turn_index))
    else:
        return None
    data[conversation_id] = entry
    _write_bindings_file(data)
    binding = _parse_entry(conversation_id, entry)
    logger.info(
        "demo_tape.turn_cursor_set",
        conversation_id=conversation_id,
        turn_index=entry["turn_index"],
    )
    return binding


def advance_after_act_complete(
    conversation_id: str, *, turn_index: int, turn_count: int
) -> str:
    """Advance the act cursor after an act END_TURN, or unbind after the last act.

    Returns ``\"advanced\"`` | ``\"unbound\"`` | ``\"noop\"`` (no binding / bad index).
    """
    if turn_count <= 0 or turn_index < 0:
        return "noop"
    binding = peek_binding(conversation_id)
    if binding is None:
        return "noop"
    next_index = turn_index + 1
    if next_index >= turn_count:
        clear_binding(conversation_id)
        logger.info(
            "demo_tape.unbound_after_last_turn",
            conversation_id=conversation_id,
            turn_index=turn_index,
            turn_count=turn_count,
            tape=str(binding.tape_path),
        )
        return "unbound"
    set_binding_turn_index(conversation_id, next_index)
    logger.info(
        "demo_tape.turn_advanced",
        conversation_id=conversation_id,
        from_index=turn_index,
        to_index=next_index,
        turn_count=turn_count,
        tape=str(binding.tape_path),
    )
    return "advanced"


def conversation_is_cloud(
    *,
    local_container_root_id: str | None,
    local_root_id: str | None,
    folder_local_root_id: str | None,
    folder_id: str | None,
) -> tuple[bool, str]:
    """Whether a conversation will take the cloud turn path on desktop.

    Mirrors desktop sidecar routing: local project folder or bare local container
    → sidecar (bypasses server tape replay); otherwise cloud.
    """
    if folder_id is not None:
        if folder_local_root_id:
            return False, "project folder is local-mode (sidecar)"
        return True, "project folder is cloud-mode"
    if local_container_root_id or local_root_id:
        return False, "bare chat has local container/root (sidecar)"
    return True, "bare cloud chat"
