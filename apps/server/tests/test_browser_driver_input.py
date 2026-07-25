"""In-sandbox driver CDP Input injection (M2 · D17): mouse/key/text mapping + coord rescale.

Drives ``Driver.input`` with a fake CDP session (no Playwright / no Chromium), asserting the
compact wire verbs map to the right CDP Input calls, frame-pixel coordinates rescale to the
viewport, unknown events are skipped, and the modifier bitmask converts. Content (key/text)
is dispatched but never returned/logged (D17) — the reply carries only the injected count.
"""

from __future__ import annotations

import pytest

from agentcore.tools.sandbox.browser.driver import Driver, _modifier_bitmask


class FakeCdp:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    async def send(self, method: str, params: dict | None = None) -> None:
        self.calls.append((method, params or {}))


def _driver(frame_w: int = 1280, frame_h: int = 800) -> Driver:
    d = Driver()
    d._cdp = FakeCdp()  # _ensure_cdp returns this without creating a real CDP session
    d._last_frame_w = frame_w
    d._last_frame_h = frame_h
    return d


@pytest.mark.asyncio
async def test_input_maps_mouse_key_text_to_cdp():
    d = _driver()
    events = [
        {"kind": "mouse", "type": "move", "x": 100, "y": 50},
        {"kind": "mouse", "type": "down", "x": 100, "y": 50, "button": "left", "click_count": 2},
        {"kind": "mouse", "type": "up", "x": 100, "y": 50, "button": "left"},
        {"kind": "mouse", "type": "wheel", "x": 10, "y": 20, "delta_x": 0, "delta_y": 120},
        {"kind": "key", "type": "down", "key": "Enter", "code": "Enter"},
        {"kind": "text", "text": "hunter2"},
    ]
    res = await d.input({"events": events})
    assert res == {"injected": 6}
    methods = [m for m, _ in d._cdp.calls]
    assert methods == [
        "Input.dispatchMouseEvent",
        "Input.dispatchMouseEvent",
        "Input.dispatchMouseEvent",
        "Input.dispatchMouseEvent",
        "Input.dispatchKeyEvent",
        "Input.insertText",
    ]
    press = d._cdp.calls[1][1]
    assert press["button"] == "left" and press["clickCount"] == 2
    wheel = d._cdp.calls[3][1]
    assert wheel["deltaY"] == 120
    assert d._cdp.calls[4][1]["key"] == "Enter" and d._cdp.calls[4][1]["code"] == "Enter"
    assert d._cdp.calls[5][1]["text"] == "hunter2"


@pytest.mark.asyncio
async def test_input_rescales_frame_coords_to_viewport():
    # Frame half the viewport (640x400 vs 1280x800) ⇒ coords double.
    d = _driver(frame_w=640, frame_h=400)
    res = await d.input({"events": [{"kind": "mouse", "type": "move", "x": 100, "y": 50}]})
    assert res == {"injected": 1}
    params = d._cdp.calls[0][1]
    assert params["x"] == 200 and params["y"] == 100


@pytest.mark.asyncio
async def test_input_identity_when_frame_matches_viewport():
    d = _driver(frame_w=1280, frame_h=800)
    await d.input({"events": [{"kind": "mouse", "type": "move", "x": 640, "y": 400}]})
    params = d._cdp.calls[0][1]
    assert params["x"] == 640 and params["y"] == 400


@pytest.mark.asyncio
async def test_input_skips_unknown_events_and_counts_valid_only():
    d = _driver()
    events = [
        {"kind": "mouse", "type": "teleport", "x": 1, "y": 1},  # bad mouse verb
        {"kind": "gamepad"},  # unknown kind
        {"kind": "text", "text": "ok"},
    ]
    res = await d.input({"events": events})
    assert res == {"injected": 1}
    assert [m for m, _ in d._cdp.calls] == ["Input.insertText"]


@pytest.mark.asyncio
async def test_input_key_modifiers_bitmask_applied():
    d = _driver()
    await d.input(
        {"events": [{"kind": "key", "type": "down", "key": "a", "modifiers": ["shift", "ctrl"]}]}
    )
    assert d._cdp.calls[0][1]["modifiers"] == 10  # shift(8) | ctrl(2)


def test_modifier_bitmask_accepts_int_list_and_rejects_bool():
    assert _modifier_bitmask(None) == 0
    assert _modifier_bitmask(0) == 0
    assert _modifier_bitmask(4) == 4
    assert _modifier_bitmask(["shift"]) == 8
    assert _modifier_bitmask(["Meta", "Alt"]) == 5  # meta(4) | alt(1)
    assert _modifier_bitmask(True) == 0  # bool is not a real bitmask


class _FakeLocator:
    """Minimal Playwright-like locator for Driver.type password gate (no Chromium)."""

    def __init__(self, *, is_password: bool) -> None:
        self.is_password = is_password
        self.filled: str | None = None

    async def evaluate(self, _js):
        return self.is_password

    async def fill(self, text: str, timeout: int = 0) -> None:
        self.filled = text


@pytest.mark.asyncio
async def test_type_hard_rejects_password_without_fill():
    d = Driver()
    loc = _FakeLocator(is_password=True)

    def _resolve(_req):
        return loc

    d._resolve_ref = _resolve  # type: ignore[method-assign]
    with pytest.raises(ValueError, match="password_blocked"):
        await d.type({"ref": "e1", "text": "hunter2"})
    assert loc.filled is None


@pytest.mark.asyncio
async def test_type_fills_non_password():
    d = Driver()
    loc = _FakeLocator(is_password=False)
    d._resolve_ref = lambda _req: loc  # type: ignore[method-assign]

    async def _page_state(*, capture):
        return {"final_url": "u", "title": "t"}

    d._page_state = _page_state  # type: ignore[method-assign]

    res = await d.type({"ref": "e2", "text": "hello"})
    assert loc.filled == "hello"
    assert res["final_url"] == "u"
