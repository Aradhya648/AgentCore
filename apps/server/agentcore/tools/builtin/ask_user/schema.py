"""Card field normalization and caps for ask_user."""

from __future__ import annotations

import json
import re
from typing import Any

# Caps so a runaway prompt can't bloat the card / event. The free-form note on the
# card always lets the user steer beyond these.
_MAX_QUESTIONS = 5  # 开场重点问题最多 5 个（对齐 Cursor 2.1 的 3–5）
_MAX_OPTIONS = 6  # 每个 choice 问题的选项上限
_MAX_OPTION_DETAIL = 120  # 单个选项的权衡说明上限（一行内）
_MAX_ASSUMPTIONS = 10

# Presentation metadata belongs in ``recommended``, not the answer-valued label.
# Reject bracketed markers only — bare「推荐」in a product name (e.g. 推荐算法) stays valid.
_LABEL_RECOMMENDATION_MARK = re.compile(
    r"[（(【\[]\s*推荐\s*[）)】\]]|[（(【\[]\s*recommended\s*[）)】\]]",
    re.IGNORECASE,
)


class ListArgError(ValueError):
    """Non-list tool arg that cannot be coerced to a JSON array (e.g. double-encoded junk)."""


class OptionLabelError(ValueError):
    """Choice label embeds recommendation markup that belongs in ``recommended`` only."""


# Markdown bullet / numbered list line → capture the item body.
_MD_LIST_ITEM_RE = re.compile(r"^\s*(?:[-*+]|\d+[.)])\s+(.+)$")


def split_markdown_list_items(text: str) -> list[str] | None:
    """If ``text`` looks like a markdown bullet/numbered list, return item bodies.

    Used by handoff ``key_points`` loose parse (models often emit ``"- a\\n- b"`` instead
    of a JSON array). Returns ``None`` when the string is not a list shape so callers can
    fall back to wrapping the whole string as a single item.
    """
    if not text or not text.strip():
        return None
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    items: list[str] = []
    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue
        m = _MD_LIST_ITEM_RE.match(stripped)
        if not m:
            return None
        body = m.group(1).strip()
        if body:
            items.append(body)
    return items or None


def coerce_list_arg(
    raw: Any, *, field: str, allow_markdown_bullets: bool = False
) -> list[Any]:
    """Accept a real list, or a single JSON-encoded array string (common model fumble).

    Empty / missing → ``[]``. A non-empty string that is not a JSON array raises
    :class:`ListArgError` so the tool can reject instead of silently dropping options.
    When ``allow_markdown_bullets`` is True, a markdown bullet/numbered list string is
    accepted as a list (handoff ``key_points``); truly bad JSON still fails.
    """
    if raw is None:
        return []
    if isinstance(raw, list):
        return raw
    if isinstance(raw, str):
        text = raw.strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            if allow_markdown_bullets:
                md_items = split_markdown_list_items(text)
                if md_items is not None:
                    return md_items
            raise ListArgError(f"{field} 须为数组；收到无法解析的 JSON 字符串。") from exc
        if isinstance(parsed, list):
            return parsed
        if allow_markdown_bullets and isinstance(parsed, str):
            md_items = split_markdown_list_items(parsed)
            if md_items is not None:
                return md_items
            return [parsed] if parsed.strip() else []
        raise ListArgError(
            f"{field} 须为数组；JSON 字符串解析结果为 {type(parsed).__name__}，不是数组。"
        )
    return []


def option_label(opt: Any) -> str:
    """The canonical label of a choice option, tolerant of both shapes.

    Options normalize to ``{label, detail?, recommended?}`` dicts, but a durable frame
    persisted before that change (or a hand-built test) may still carry a bare string —
    both the live tool and a resume read labels through here so an old paused turn still
    settles. The label is the answer value (答复模型 α): no separate wire value exists.
    """
    if isinstance(opt, dict):
        return str(opt.get("label") or "").strip()
    return str(opt).strip()


def assert_clean_option_label(label: str) -> None:
    """Fail closed when label duplicates the UI「推荐」channel.

    Does not rewrite the string — the tool rejects so the model retries with a clean
    label + ``recommended=true``.
    """
    if _LABEL_RECOMMENDATION_MARK.search(label):
        raise OptionLabelError(
            f"options.label 禁止写入推荐标记（收到 {label!r}）；"
            "倾向只设 recommended=true，label 保持干净选项名。"
        )


def normalize_options(
    raw: Any,
    *,
    max_options: int = _MAX_OPTIONS,
) -> list[dict[str, Any]]:
    """Cap choice options, accepting either bare strings or rich objects.

    Default cap is 6 (ordinary choice). ``card=risk_ack`` may raise the cap to 10.
    A bare ``"Postgres"`` becomes ``{"label": "Postgres"}``; an object may add a one-line
    ``detail`` (the trade-off shown under the label), ``recommended`` (the asker's
    advised option — advisory only, never a pre-selection), and ``action`` (a desktop
    client action such as ``open_local_project`` / ``bind_local_folder`` — unknown values
    drop so a hallucinated action never reaches the wire). Empty-label entries drop, and
    only the FIRST
    ``recommended`` survives (至多一个推荐项), so the card shows one clear「推荐」without
    a wall of badges. Labels that embed recommendation markup (e.g. ``（推荐）``) raise
    :class:`OptionLabelError` — no silent strip.
    """
    cap = max(1, int(max_options))
    items = coerce_list_arg(raw, field="options")
    out: list[dict[str, Any]] = []
    recommended_taken = False
    for it in items:
        label = option_label(it)
        if not label:
            continue
        assert_clean_option_label(label)
        opt: dict[str, Any] = {"label": label}
        if isinstance(it, dict):
            detail = str(it.get("detail") or "").strip()
            if detail:
                opt["detail"] = detail[:_MAX_OPTION_DETAIL]
            if bool(it.get("recommended")) and not recommended_taken:
                opt["recommended"] = True
                recommended_taken = True
            action = str(it.get("action") or "").strip()
            if action in (
                "open_local_project",
                "bind_local_folder",
                "grant_readonly_folder",
                "grant_organize_folder",
            ):
                opt["action"] = action
            # organize_plan structured fields (passed through for plan binding).
            op = str(it.get("op") or "").strip()
            if op in ("move", "copy", "delete", "mkdir"):
                opt["op"] = op
                if op in ("move", "copy"):
                    src = str(it.get("source") or "").strip()
                    dst = str(it.get("destination") or "").strip()
                    if src:
                        opt["source"] = src
                    if dst:
                        opt["destination"] = dst
                else:
                    p = str(it.get("path") or "").strip()
                    if p:
                        opt["path"] = p
            # daily_review structured fields (server apply on confirm).
            review_kind = str(it.get("review_kind") or "").strip()
            if review_kind in ("preference", "profile", "topic", "rule", "doc"):
                opt["review_kind"] = review_kind
                body = str(it.get("body") or "").strip()
                if body:
                    opt["body"] = body[:4000]
                slug = str(it.get("slug") or "").strip()
                if slug:
                    opt["slug"] = slug[:64]
                section = str(it.get("section") or "").strip()
                if section:
                    opt["section"] = section[:64]
                rpath = str(it.get("path") or "").strip()
                if rpath and review_kind == "doc":
                    opt["path"] = rpath[:240]
        out.append(opt)
        if len(out) >= cap:
            break
    return out


def normalize_assumptions(raw: Any) -> list[dict[str, Any]]:
    """Cap + id the 起步计划 chips, dropping malformed / empty-label entries."""
    items = coerce_list_arg(raw, field="assumptions")
    out: list[dict[str, Any]] = []
    for i, it in enumerate(items[:_MAX_ASSUMPTIONS]):
        if not isinstance(it, dict):
            continue
        label = str(it.get("label") or "").strip()
        if not label:
            continue
        out.append({"id": f"a{i}", "label": label, "value": str(it.get("value") or "").strip()})
    return out


def normalize_questions(
    raw: Any,
    *,
    max_options: int = _MAX_OPTIONS,
) -> list[dict[str, Any]]:
    """Cap (≤5) + id the questions, normalizing kind/options/multiple/default.

    ``default`` is optional here (unlike the old kickoff): an opening question should
    pre-fill one, but a mid-task fork usually wants the user to actively choose, so it
    is left empty when the CEO omits it. ``max_options`` forwards to
    :func:`normalize_options` (raised for ``card=risk_ack``).
    """
    items = coerce_list_arg(raw, field="questions")
    out: list[dict[str, Any]] = []
    for i, it in enumerate(items[:_MAX_QUESTIONS]):
        if not isinstance(it, dict):
            continue
        prompt = str(it.get("prompt") or "").strip()
        if not prompt:
            continue
        kind = "text" if str(it.get("kind") or "").strip() == "text" else "choice"
        if kind == "choice":
            options = normalize_options(it.get("options"), max_options=max_options)
            multiple = bool(it.get("multiple") or False)
        else:
            options = []
            multiple = False
        out.append(
            {
                "id": f"q{i}",
                "prompt": prompt,
                "kind": kind,
                "options": options,
                "multiple": multiple,
                "default": str(it.get("default") or "").strip(),
            }
        )
    return out
