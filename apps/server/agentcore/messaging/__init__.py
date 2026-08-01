"""消息 page (找人 IM) domain: people-search, dms, messages, blocks, privacy.

See ``docs/05-平台与运维/消息IM.md``. The frontend chat core is shared with the
对话 page (找 AI); the backend is a separate set of tables/repos and this service.
"""

from agentcore.messaging.events import ChatEventPublisher, NullChatEventPublisher
from agentcore.messaging.hub import (
    ChatHub,
    HubChatEventPublisher,
    Subscription,
    default_chat_hub,
)
from agentcore.messaging.service import (
    AttachmentUpload,
    ChatView,
    DirectoryView,
    FriendRequestBox,
    MessagePage,
    MessagingService,
    ProfileView,
)

__all__ = [
    "AttachmentUpload",
    "ChatEventPublisher",
    "ChatHub",
    "ChatView",
    "DirectoryView",
    "FriendRequestBox",
    "HubChatEventPublisher",
    "MessagePage",
    "MessagingService",
    "NullChatEventPublisher",
    "ProfileView",
    "Subscription",
    "default_chat_hub",
]
