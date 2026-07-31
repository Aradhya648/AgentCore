"""SQLAlchemy ORM model definitions, split by domain.

This ORM is the single source of truth for the AgentCore schema; structure is
applied via Alembic migrations (``alembic check`` must report zero drift).

This package was split out of a single ``models.py`` along the same domain seams as
``db/repositories`` (auth / billing / chat / conversations / devices / runs /
users). Importing the package imports every model module, so all tables
register on ``Base.metadata`` exactly as before (Alembic's ``env.py`` and
``Base.metadata.create_all`` see the full set). This ``__init__`` re-exports the full
class surface so the historical import path — ``from agentcore.db.models import X`` —
keeps working unchanged across the codebase; ``_new_uuid`` is re-exported because it
was a module-level name on the original module.
"""

from ._helpers import _new_uuid
from .admin_audit import AdminAuditLog
from .admin_mfa import AdminMfa
from .agent_audit import AgentAuditEvent
from .auth import Credentials, Invite, RefreshToken, UserLlmProvider
from .billing import CostCall, CostEvent
from .boards import Board
from .browser import BrowserTakeoverRow
from .chat import Chat, ChatMember, ChatMessage
from .conversations import (
    Conversation,
    ConversationExternalGrant,
    ConversationShare,
    Folder,
    MemoryUpdateRow,
    Message,
    MessageBookmark,
)
from .devices import PushDeviceRow
from .documents import Document
from .feedback import FeedbackRow
from .llm_profiles import LlmModelProfile
from .notices import ProductNoticeDismissalRow, ProductNoticeRow
from .runs import (
    HandoffJob,
    PausedTurnRow,
    RunSessionRow,
    TurnJournalRow,
    TurnLeaseRow,
    TurnMetricsRow,
    TurnStreamStateRow,
)
from .shared_spaces import SharedSpace, SharedSpaceEvent, SharedSpaceMember
from .simulation import SimAgent, SimEvent, SimTick, SimulationRun
from .standing_tasks import StandingTask, StandingTaskRun
from .user_workflows import UserWorkflow
from .users import User, UserBlock, UserDirectorySettings

__all__ = [
    "AdminAuditLog",
    "AgentAuditEvent",
    "AdminMfa",
    "Board",
    "BrowserTakeoverRow",
    "Chat",
    "ChatMember",
    "ChatMessage",
    "Conversation",
    "ConversationExternalGrant",
    "ConversationShare",
    "CostCall",
    "CostEvent",
    "Credentials",
    "Document",
    "FeedbackRow",
    "Folder",
    "HandoffJob",
    "Invite",
    "LlmModelProfile",
    "MemoryUpdateRow",
    "Message",
    "MessageBookmark",
    "PausedTurnRow",
    "ProductNoticeDismissalRow",
    "ProductNoticeRow",
    "PushDeviceRow",
    "RefreshToken",
    "RunSessionRow",
    "SharedSpace",
    "SharedSpaceEvent",
    "SharedSpaceMember",
    "SimAgent",
    "SimEvent",
    "SimTick",
    "SimulationRun",
    "StandingTask",
    "StandingTaskRun",
    "TurnJournalRow",
    "TurnLeaseRow",
    "TurnMetricsRow",
    "TurnStreamStateRow",
    "User",
    "UserBlock",
    "UserDirectorySettings",
    "UserLlmProvider",
    "UserWorkflow",
    "_new_uuid",
]
