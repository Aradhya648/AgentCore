"""Data access layer (Repository pattern), split by domain.

Each repository handles CRUD for a single model:
- Only data access, no business logic
- Uses select() builder pattern
- Pagination returns (data, total_count)
- Default sort: created_at desc
- commit() and refresh() handled internally

This package was split out of a single ``repositories.py`` along domain seams
(file-splitting.mdc). This ``__init__`` re-exports the full public surface so the
historical import path — ``from agentcore.db.repositories import XRepository`` —
keeps working unchanged across the codebase. ``_ilike_pattern`` is re-exported
because the global-search tests import it directly.
"""

# Lease repo lives under runtime (swappable backend seam); re-exported for DB consumers.
from agentcore.runtime.leases.repo import TurnLeaseRepository  # noqa: E402

from ._base import _UNSET, _ilike_pattern
from .admin_audit import AdminAuditRepository
from .admin_mfa import AdminMfaRepository
from .agent_audit import AgentAuditEventRepository
from .auth import (
    CredentialsRepository,
    InviteRepository,
    RefreshTokenRepository,
    UserLlmProviderRepository,
)
from .billing import CostEventRepository
from .boards import BoardRepository
from .bookmarks import BookmarkRepository
from .browser import BrowserTakeoverRepository
from .chat import ChatRepository
from .conversation_shares import ConversationShareRepository
from .conversations import ConversationRepository
from .devices import PushDeviceRepository
from .external_grants import ExternalGrantRepository
from .documents import DocumentRepository
from .feedback import FeedbackRepository
from .folders import FolderRepository
from .llm_profiles import LlmModelProfileRepository
from .memory_updates import MemoryUpdateRepository
from .messages import MessageRepository
from .runs import (
    HandoffJobRepository,
    PausedTurnRepository,
    RunSessionRepository,
    TurnJournalRepository,
    TurnMetricsRepository,
)
from .shared_spaces import SharedSpaceRepository
from .simulation import SimulationRepository
from .standing_tasks import StandingTaskRepository, StandingTaskRunRepository
from .stream_state import TurnStreamStateRepository
from .users import (
    UserBlockRepository,
    UserDirectoryRepository,
    UserRepository,
)

__all__ = [
    "_UNSET",
    "_ilike_pattern",
    "AdminAuditRepository",
    "AgentAuditEventRepository",
    "AdminMfaRepository",
    "BookmarkRepository",
    "BoardRepository",
    "BrowserTakeoverRepository",
    "ChatRepository",
    "ConversationRepository",
    "ConversationShareRepository",
    "CostEventRepository",
    "DocumentRepository",
    "CredentialsRepository",
    "ExternalGrantRepository",
    "FeedbackRepository",
    "FolderRepository",
    "HandoffJobRepository",
    "InviteRepository",
    "LlmModelProfileRepository",
    "MemoryUpdateRepository",
    "MessageRepository",
    "PausedTurnRepository",
    "PushDeviceRepository",
    "RefreshTokenRepository",
    "RunSessionRepository",
    "SharedSpaceRepository",
    "SimulationRepository",
    "StandingTaskRepository",
    "StandingTaskRunRepository",
    "TurnJournalRepository",
    "TurnLeaseRepository",
    "TurnMetricsRepository",
    "TurnStreamStateRepository",
    "UserBlockRepository",
    "UserDirectoryRepository",
    "UserLlmProviderRepository",
    "UserRepository",
]
