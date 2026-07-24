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
    """Return a :class:`VisionReader` iff a vision provider is configured, else ``None``.

    ``None`` is the default posture (no ``VISION_API_KEY``): ``board_read`` then returns a
    clean「读图能力未配置」error. Setting the key flips it on with no other code change
    (§九.4). The only provider today is Qwen-VL (DashScope OpenAI-compatible endpoint).
    """
    s = settings if settings is not None else _default_settings
    if not s.vision_api_key:
        return None
    logger.info("vision.reader_built", model=s.vision_model)
    return QwenVLReader(
        api_key=s.vision_api_key,
        base_url=s.vision_base_url,
        model=s.vision_model,
        timeout_seconds=s.vision_timeout_seconds,
    )
