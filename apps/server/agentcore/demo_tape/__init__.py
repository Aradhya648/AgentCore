"""Dev-only server-side demo tape replay (product screen-recording aid).

Import hooks from ``agentcore.demo_tape.hooks`` at call sites — keep this package
init light so export scripts do not pull the player / suspension graph.
"""

from agentcore.demo_tape.schema import DEMO_TAPE_FRAME_KEY, is_demo_tape_frame

__all__ = [
    "DEMO_TAPE_FRAME_KEY",
    "is_demo_tape_frame",
]
