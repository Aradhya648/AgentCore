"""Re-export the ORM row — defined in ``db.models.runs`` (schema source of truth)."""

from agentcore.db.models.runs import TurnLeaseRow

__all__ = ["TurnLeaseRow"]
