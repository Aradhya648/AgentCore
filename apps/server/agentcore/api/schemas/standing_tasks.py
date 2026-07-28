"""Standing task / inbox API schemas (L1 schedule + L2a webhook)."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from agentcore.api.schemas.conversations import PermissionAxesModel
from agentcore.standing_tasks.schedule import infer_schedule_preset
from agentcore.standing_tasks.webhook import webhook_path

TriggerKind = Literal["schedule", "webhook"]
TriggerSource = Literal["schedule", "webhook", "manual"]


class CreateStandingTaskRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    goal: str = Field(..., min_length=1)
    folder_id: str
    trigger_kind: TriggerKind = "schedule"
    # Desktop wire: schedule_preset (+ cron when custom). ``preset`` accepted as alias.
    cron: str | None = None
    schedule_preset: str | None = None
    preset: str | None = Field(None, exclude=True)
    permission_axes: PermissionAxesModel | None = None
    enabled: bool = True

    @model_validator(mode="after")
    def _require_schedule_or_webhook(self) -> "CreateStandingTaskRequest":
        preset = self.schedule_preset or self.preset
        object.__setattr__(self, "schedule_preset", preset)
        if self.trigger_kind == "webhook":
            if self.cron or preset:
                raise ValueError("trigger_kind=webhook 时不要传 schedule_preset / cron")
            return self
        if not self.cron and not preset:
            raise ValueError("须提供 schedule_preset 或 cron")
        if preset and preset.strip().lower() != "custom" and self.cron:
            raise ValueError("命名 schedule_preset 时不要同时传 cron")
        if preset and preset.strip().lower() == "custom" and not self.cron:
            raise ValueError("schedule_preset=custom 时须提供 cron")
        return self


class UpdateStandingTaskRequest(BaseModel):
    name: str | None = Field(None, min_length=1, max_length=200)
    goal: str | None = Field(None, min_length=1)
    trigger_kind: TriggerKind | None = None
    cron: str | None = None
    schedule_preset: str | None = None
    preset: str | None = Field(None, exclude=True)
    permission_axes: PermissionAxesModel | None = None
    enabled: bool | None = None

    @model_validator(mode="after")
    def _normalize_schedule(self) -> "UpdateStandingTaskRequest":
        preset = self.schedule_preset or self.preset
        if preset is not None:
            object.__setattr__(self, "schedule_preset", preset)
        if self.trigger_kind == "webhook" and (self.cron or preset):
            raise ValueError("切换到 webhook 时不要传 schedule_preset / cron")
        if (
            preset
            and preset.strip().lower() != "custom"
            and self.cron
        ):
            raise ValueError("命名 schedule_preset 时不要同时传 cron")
        if preset and preset.strip().lower() == "custom" and not self.cron:
            raise ValueError("schedule_preset=custom 时须提供 cron")
        return self


class StandingTaskSummary(BaseModel):
    id: str
    name: str
    goal: str
    folder_id: str
    trigger_kind: TriggerKind = "schedule"
    cron: str | None = None
    schedule_preset: str | None = None
    permission_axes: PermissionAxesModel
    enabled: bool
    next_run_at: datetime | None = None
    conversation_id: str | None = None
    last_run_at: datetime | None = None
    webhook_id: str | None = None
    webhook_url: str | None = None
    # One-shot plaintext; only set on create / rotate responses.
    webhook_secret: str | None = None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}

    @classmethod
    def from_row(
        cls,
        row,
        *,
        webhook_secret: str | None = None,
    ) -> "StandingTaskSummary":
        kind: TriggerKind = getattr(row, "trigger_kind", None) or "schedule"
        wid = getattr(row, "webhook_id", None)
        cron = row.cron
        return cls(
            id=row.id,
            name=row.name,
            goal=row.goal,
            folder_id=row.folder_id,
            trigger_kind=kind,
            cron=cron,
            schedule_preset=infer_schedule_preset(cron) if cron else None,
            permission_axes=PermissionAxesModel.model_validate(row.permission_axes or {}),
            enabled=row.enabled,
            next_run_at=row.next_run_at,
            conversation_id=row.conversation_id,
            last_run_at=row.last_run_at,
            webhook_id=wid,
            webhook_url=webhook_path(wid) if wid and kind == "webhook" else None,
            webhook_secret=webhook_secret,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )


class RotateWebhookSecretResponse(BaseModel):
    webhook_id: str
    webhook_url: str
    webhook_secret: str


class StandingTaskRunSummary(BaseModel):
    id: str
    standing_task_id: str
    conversation_id: str | None = None
    user_message_id: str | None = None
    status: Literal["running", "succeeded", "failed", "awaiting_user"]
    trigger_source: TriggerSource = "schedule"
    summary: str | None = None
    error: str | None = None
    acked_at: datetime | None = None
    created_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    task_name: str | None = None

    model_config = {"from_attributes": True}


class StandingTaskRunListResponse(BaseModel):
    items: list[StandingTaskRunSummary]
    badge: int = 0


class TriggerStandingTaskResponse(BaseModel):
    run_id: str
