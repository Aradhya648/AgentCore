"""Build the optional VisionReader from settings (AI协作白板.md §九.4「插上即用」)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from agentcore.config import settings as _default_settings
from agentcore.core.logging import get_logger
from agentcore.vision.protocol import VisionReader
from agentcore.vision.qwen import QwenVLReader

if TYPE_CHECKING:
    from agentcore.config.settings import Settings

logger = get_logger(__name__)


def build_vision_reader(settings: Settings | None = None) -> VisionReader | None:
    """Return a :class:`VisionReader` iff platform vision is enabled, else ``None``.

    Gates (all required):

    - ``billing_mode=platform`` — BYOK deployments never enable 识图 (no platform quota).
    - non-empty ``VISION_API_KEY`` — empty → ``board_read`` clean「读图能力未配置」.

    The HTTP shape is OpenAI-compatible multimodal (``image_url`` data URL); the
    concrete class remains ``QwenVLReader`` regardless of ``VISION_MODEL`` (default
    ``kimi-k2.5`` on the operator relay).
    """
    s = settings if settings is not None else _default_settings
    if getattr(s, "billing_mode", "byok") != "platform":
        return None
    if not s.vision_api_key or not (s.vision_base_url or "").strip():
        return None
    logger.info("vision.reader_built", model=s.vision_model)
    return QwenVLReader(
        api_key=s.vision_api_key,
        base_url=s.vision_base_url,
        model=s.vision_model,
        timeout_seconds=s.vision_timeout_seconds,
    )
