"""Sidecar JSON-RPC server package."""

from agentcore.runtime.pipeline import resume_chat_pipeline, run_chat_pipeline
from agentcore.sidecar.server_pkg.core import SidecarServer
from agentcore.sidecar.server_pkg.result import parse_decision, trim_result

# Back-compat names for any direct imports of private helpers.
_parse_decision = parse_decision
_trim_result = trim_result

__all__ = [
    "SidecarServer",
    "run_chat_pipeline",
    "resume_chat_pipeline",
    "parse_decision",
    "trim_result",
    "_parse_decision",
    "_trim_result",
]
