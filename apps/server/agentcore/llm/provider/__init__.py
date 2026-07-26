"""Provider package — protocol, OpenAI-compatible implementation, multi-vendor router."""

from agentcore.llm.provider.openai_compatible import OpenAICompatibleProvider
from agentcore.llm.provider.protocol import (
    BACKOFF_MULTIPLIER,
    INITIAL_BACKOFF,
    MAX_RETRIES,
    LLMChunk,
    LLMMessage,
    LLMProvider,
    LLMRequest,
    LLMResponse,
    TokenUsage,
    ToolCall,
)
from agentcore.llm.provider.router import ProviderRouter

# PlatformProvider is imported from agentcore.llm.provider.platform directly
# (not re-exported here) to avoid credentials ↔ profiles ↔ provider init cycles.

__all__ = [
    "BACKOFF_MULTIPLIER",
    "INITIAL_BACKOFF",
    "LLMChunk",
    "LLMMessage",
    "LLMProvider",
    "LLMRequest",
    "LLMResponse",
    "MAX_RETRIES",
    "OpenAICompatibleProvider",
    "ProviderRouter",
    "TokenUsage",
    "ToolCall",
]
