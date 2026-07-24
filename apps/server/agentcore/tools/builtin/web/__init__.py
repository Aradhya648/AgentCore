"""Web tools: ``web_search`` (via self-hosted SearXNG) + ``read_url`` (fetch +
extract). The direct-egress ``read_url`` shares networking resilience from
``_net`` (per-host circuit breaker, honest error messages, tuned timeouts)."""

from agentcore.tools.builtin.web.read_url import ReadUrlTool
from agentcore.tools.builtin.web.search import WebSearchTool

__all__ = ["ReadUrlTool", "WebSearchTool"]
