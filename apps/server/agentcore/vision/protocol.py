"""VisionReader — the port a vision model plugs into for board 读图 (AI协作白板.md §九.4).

``board_read`` rasterizes hand-drawn / screenshot board elements to a PNG and asks a
``VisionReader`` to turn that image into a :class:`VisionReading` (the text the CEO reasons
over + the sub-call's token usage so the spend can be billed). The port is deliberately one
async method: input PNG (base64) + a prompt, output a reading.

A reference implementation ships (``QwenVLReader``); a provider is enabled by setting
``VISION_API_KEY`` (§九.4「插上即用」). Empty key ⇒ the pipeline injects ``None`` and
``board_read`` returns a clean「读图能力未配置」error rather than pretending. A new provider
(异构 API like Claude/Gemini) is one more ``VisionReader`` that returns a ``VisionReading``;
§九.1–九.3 (rasterize + channel + tool) are untouched — that is the seam.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Protocol, runtime_checkable

from agentcore.llm.provider.protocol import TokenUsage


@dataclass(frozen=True)
class VisionReading:
    """A vision model's reading of a board PNG + the usage to bill it (§九.4 Gap ②).

    ``text`` is the reading the CEO reasons over (``board_read``'s tool output). ``usage`` /
    ``model`` carry the sub-call's token cost so ``board_read`` can price it into the turn's
    ``cost_events`` ledger — the vision model is SEPARATE from the run's DeepSeek, so its
    spend is its own priced ledger row, never folded into the run's usage. A reader with no
    usage signal (a stub) leaves ``usage`` zero, and ``board_read`` then bills nothing.
    """

    text: str
    usage: TokenUsage = field(default_factory=TokenUsage)
    model: str = ""


@runtime_checkable
class VisionReader(Protocol):
    """Reads an image (PNG, base64) and returns a :class:`VisionReading`."""

    async def read(self, png_base64: str, prompt: str) -> VisionReading:
        """Return a :class:`VisionReading` of ``png_base64`` guided by ``prompt``."""
        ...
