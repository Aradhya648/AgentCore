"""L3 team-browser (M0) sandbox session surface — long-lived Chromium in gVisor.

See ``docs/06-规划/内置浏览器与Agent浏览器提案.md`` (D9–D11) and the channel PoC
(``apps/server/scripts/poc_browser_gvisor``). This package holds the sandbox-side
control channel (driver + stdio RPC), the network isolation (netns + veth), the
SSRF egress proxy, and the runsc session orchestration.
"""

from agentcore.tools.sandbox.browser.protocol import (
    BROWSER_ACTIONS,
    STATE_CHANGING_ACTIONS,
    BrowserCommand,
    BrowserCommandResult,
    BrowserSessionAcquireError,
    BrowserDriverCrashedError,
    BrowserSession,
    BrowserSessionError,
    BrowserSessionProvider,
    BrowserSessionRequest,
    BrowserSessionsBusyError,
)

__all__ = [
    "BROWSER_ACTIONS",
    "STATE_CHANGING_ACTIONS",
    "BrowserCommand",
    "BrowserCommandResult",
    "BrowserDriverCrashedError",
    "BrowserSession",
    "BrowserSessionAcquireError",
    "BrowserSessionError",
    "BrowserSessionProvider",
    "BrowserSessionRequest",
    "BrowserSessionsBusyError",
]
