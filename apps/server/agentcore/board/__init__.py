"""AI 协作白板 (whiteboard) server-side: the channel that lets a server tool apply
structured ops to the user's open whiteboard canvas via the bound desktop.

See ``AI协作白板.md`` §六 (M2 工具/通道) for the design.
"""

from agentcore.board.channel import BoardChannel, BoardOpError

__all__ = ["BoardChannel", "BoardOpError"]
