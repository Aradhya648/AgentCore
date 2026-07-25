"""Conversation and folder (project = workspace) request/response schemas."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from agentcore.core.types import PermissionPreset


class CreateConversationRequest(BaseModel):
    title: str | None = None
    # File the new chat into a project at creation. Born into that project's
    # shared workspace (no session-level local_* columns written). None = 裸聊.
    folder_id: str | None = None
    # Desktop's default local container root for a 裸聊 (local-first intent).
    # Recorded only when ``folder_id`` is None; project chats inherit the project's
    # binding instead.
    local_container_root_id: str | None = Field(None, max_length=200)
    # Session permission mode. Omit → seed from the user's autonomy default
    # (always_ask→observe / first_grant→workspace / full_auto→full_trust).
    permission_preset: PermissionPreset | None = None


class ConversationSummary(BaseModel):
    id: str
    title: str | None
    updated_at: datetime
    created_at: datetime
    message_count: int = 0
    # Project membership; None = 裸聊. When set, effective workspace is the project's.
    folder_id: str | None = None
    # Desktop local-first intent for a 裸聊; moot once foldered.
    local_container_root_id: str | None = None
    pinned: bool = False
    archived: bool = False
    # Session permission mode (运行时单一真相源).
    permission_preset: PermissionPreset = PermissionPreset.WORKSPACE
    # 深度研究自治（会话级旗标；full_trust 蕴含同效，见 runtime.deep_research_auto）。
    deep_research_auto: bool = False
    # 会话级模型组合（模型组合配置）。None = 跟随账号默认组合。
    model_profile_id: str | None = None

    model_config = {"from_attributes": True}


class ConversationListResponse(BaseModel):
    data: list[ConversationSummary]
    total: int
    page: int
    page_size: int


class UpdateConversationRequest(BaseModel):
    title: str | None = None
    pinned: bool | None = None
    archived: bool | None = None
    # 深度研究自治：省略 = 不变；显式 true/false 切换会话旗标（设置页 UI 另批）。
    deep_research_auto: bool | None = None
    # 会话级模型组合：省略 = 不变；显式 uuid = 挂组合；显式 null = 清除，跟随账号默认。
    model_profile_id: str | None = None


class PermissionPresetUpdate(BaseModel):
    """Switch the conversation's permission mode mid-session."""

    permission_preset: PermissionPreset


class CreateFolderRequest(BaseModel):
    """Create a project (= workspace). ``mode`` is required and immutable after create."""

    model_config = {"extra": "forbid"}

    name: str
    mode: Literal["local", "cloud"]
    # Required when ``mode=local``; forbidden when ``mode=cloud``.
    local_root_id: str | None = Field(None, max_length=200)
    local_subpath: str | None = Field(None, max_length=400)

    @model_validator(mode="after")
    def _validate_mode_binding(self) -> "CreateFolderRequest":
        if self.mode == "local":
            if not self.local_root_id:
                raise ValueError("local 模式必须提供 local_root_id")
            # Empty string ≡ unbound-at-root; store as NULL for stable reuse lookup.
            if self.local_subpath == "":
                self.local_subpath = None
        elif self.local_root_id is not None or self.local_subpath is not None:
            raise ValueError("cloud 模式不能绑定本地路径")
        return self


class UpdateFolderRequest(BaseModel):
    """Rename only — project workspace binding is immutable after create."""

    name: str | None = None


class FolderSummary(BaseModel):
    id: str
    name: str
    mode: Literal["local", "cloud"]
    local_root_id: str | None = None
    local_subpath: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_folder(cls, folder) -> "FolderSummary":
        return cls(
            id=folder.id,
            name=folder.name,
            mode="local" if folder.local_root_id else "cloud",
            local_root_id=folder.local_root_id,
            local_subpath=folder.local_subpath,
            created_at=folder.created_at,
            updated_at=folder.updated_at,
        )


class FolderGroup(BaseModel):
    """A project plus the conversations it holds (grouped sidebar payload)."""

    id: str
    name: str
    mode: Literal["local", "cloud"]
    local_root_id: str | None = None
    local_subpath: str | None = None
    conversations: list[ConversationSummary]


class GroupedConversationsResponse(BaseModel):
    folders: list[FolderGroup]
    ungrouped: list[ConversationSummary]
