"""Local→云 handoff: snapshot / dispatch a cloud job / list / diff / apply (P2e)."""

import asyncio

from fastapi import APIRouter, Depends

from agentcore.api.dependencies import (
    AuthUser,
    get_conversation_repo,
    get_cost_event_repo,
    get_handoff_job_repo,
)
from agentcore.api.schemas import (
    ApplyHandoffRequest,
    DispatchHandoffRequest,
    HandoffDiffResponse,
    HandoffFileChange,
    HandoffJobListResponse,
    HandoffJobSummary,
)
from agentcore.api.sse import sse_response
from agentcore.conversation.quota import QuotaLimits, enforce_quota
from agentcore.conversation.rate_limit import enforce_user_message_rate_limit
from agentcore.conversation.scratch import resolve_conversation_local_binding
from agentcore.conversation.service import dispatch_handoff
from agentcore.core.error_codes import ErrorCode
from agentcore.core.errors import ConflictError, NotFoundError, ValidationError
from agentcore.core.logging import get_logger
from agentcore.db.repositories import (
    ConversationRepository,
    CostEventRepository,
    HandoffJobRepository,
)
from agentcore.runtime.events import (
    EventSink,
    error_event,
    handoff_apply_done,
    handoff_snapshot_done,
)
from agentcore.storage import SnapshotNotFound
from agentcore.workspace.handoff import snapshot_local
from agentcore.workspace.handoff_apply import ApplySelection, apply_handoff
from agentcore.workspace.handoff_diff import compute_handoff_diff
from agentcore.workspace.locate import LocalBinding, build_workspace

from ._helpers import _get_owned_conversation, _require_owned_conversation

router = APIRouter(prefix="/conversations", tags=["conversations"])

logger = get_logger(__name__)


async def _run_handoff(
    *,
    user_id: str,
    folder_id: str | None,
    conversation_id: str,
    binding: LocalBinding,
    sink: EventSink,
) -> None:
    """Drive a local→云 handoff snapshot to completion over its SSE sink (P2e / e1).

    Mirrors ``stream_chat``'s shape: the ARCHIVE op is emitted on ``sink`` (the
    bound desktop fulfils it via the ops resolve endpoint), and on success a
    ``handoff_snapshot_done`` carrying the new snapshot id is emitted before the
    stream closes. Any failure is surfaced as an inline ``error`` event (never an
    unhandled crash on this detached task), so the client always learns the outcome.
    """
    try:
        ref = await snapshot_local(
            user_id=user_id,
            folder_id=folder_id,
            conversation_id=conversation_id,
            binding=binding,
            sink=sink,
        )
        sink.emit(
            handoff_snapshot_done(
                snapshot_id=ref.snapshot_id,
                conversation_id=conversation_id,
                size_bytes=ref.size_bytes,
            )
        )
    except Exception as e:
        logger.warning("handoff.failed", conversation_id=conversation_id, error=str(e))
        sink.emit(error_event(ErrorCode.HANDOFF_FAILED, str(e)))
    finally:
        if not sink._closed:
            sink.close()


@router.post("/{conversation_id}/workspace/handoff")
async def handoff_local_workspace(
    conversation_id: str,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
):
    """Snapshot a local-mode workspace to the cloud over the channel (双模式工作区 P2e / e1).

    Local-mode files live on the user's machine, so the post-turn OSS backup skips
    them; this is the explicit, on-demand 本地→云 snapshot (§四). Streams SSE: a
    ``workspace_op_required`` (the ARCHIVE op) the bound desktop fulfils, then a
    ``handoff_snapshot_done`` carrying the new snapshot id (it lands in the same
    snapshot list / restore / download as cloud-mode versions). 422 when the
    conversation is not in local mode — a cloud workspace already snapshots itself,
    and there is nothing on the user's disk to fetch.
    """
    conv = await _get_owned_conversation(conversation_id, user.user_id, conv_repo)
    binding = resolve_conversation_local_binding(
        local_root_id=conv.local_root_id,
        local_subpath=conv.local_subpath,
        label="workspace",
    )
    if binding is None:
        raise ValidationError("该对话不是本地模式")

    sink = EventSink()
    task = asyncio.create_task(
        _run_handoff(
            user_id=user.user_id,
            folder_id=None,
            conversation_id=conversation_id,
            binding=binding,
            sink=sink,
        )
    )
    return sse_response(sink, producer=task)


@router.post("/{conversation_id}/workspace/handoff/dispatch")
async def dispatch_handoff_job(
    conversation_id: str,
    body: DispatchHandoffRequest,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    cost_repo: CostEventRepository = Depends(get_cost_event_repo),
):
    """Hand a task off to a cloud team seeded from the local workspace (P2e / e2).

    The 本地→云 交接 (§四): snapshot the user's local files, then run an Agent team on
    that snapshot in the cloud — autonomously, in the background — so a parallel team
    is not bottlenecked by the single desktop channel. Streams SSE: a
    ``workspace_op_required`` (the ARCHIVE op) the bound desktop fulfils, then a
    ``handoff_job_started`` carrying the job id; the cloud run continues detached
    after the stream closes (poll ``GET …/handoff/jobs`` for its status). 422 when
    the conversation is not in local mode (nothing local to hand off).

    Gated like ``send_message`` (it spends tokens): rate limit → ownership → quota.
    """
    await enforce_user_message_rate_limit(user.user_id)
    conv = await _get_owned_conversation(conversation_id, user.user_id, conv_repo)
    await enforce_quota(cost_repo, user.user_id, limits=QuotaLimits.for_user(user))

    binding = resolve_conversation_local_binding(
        local_root_id=conv.local_root_id,
        local_subpath=conv.local_subpath,
        label="workspace",
    )
    if binding is None:
        raise ValidationError("该对话不是本地模式")

    sink = EventSink()
    task = asyncio.create_task(
        dispatch_handoff(
            conversation_id=conversation_id,
            user_id=user.user_id,
            folder_id=None,
            binding=binding,
            task=body.task,
            sink=sink,
        )
    )
    return sse_response(sink, producer=task)


@router.get("/{conversation_id}/handoff/jobs", response_model=HandoffJobListResponse)
async def list_handoff_jobs(
    conversation_id: str,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    job_repo: HandoffJobRepository = Depends(get_handoff_job_repo),
):
    """A conversation's local→云 handoff jobs, newest first (双模式工作区 P2e / e2).

    Backs the client's job badge / PR list: poll this to learn when a dispatched
    cloud run finishes (status succeeded / failed). 404 if the conversation is not
    owned.
    """
    await _require_owned_conversation(conversation_id, user.user_id, conv_repo)
    jobs = await job_repo.list_for_source(conversation_id, user_id=user.user_id)
    data = [HandoffJobSummary.model_validate(j) for j in jobs]
    return HandoffJobListResponse(data=data, total=len(data))


@router.get("/{conversation_id}/handoff/jobs/{job_id}", response_model=HandoffJobSummary)
async def get_handoff_job(
    conversation_id: str,
    job_id: str,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    job_repo: HandoffJobRepository = Depends(get_handoff_job_repo),
):
    """One handoff job's status + result snapshots (双模式工作区 P2e / e2).

    404 if the conversation is not owned, or the job is unknown / belongs to a
    different source conversation.
    """
    await _require_owned_conversation(conversation_id, user.user_id, conv_repo)
    job = await job_repo.get_by_id(job_id, user_id=user.user_id)
    if job is None or job.source_conversation_id != conversation_id:
        raise NotFoundError("交接任务不存在")
    return HandoffJobSummary.model_validate(job)


@router.get(
    "/{conversation_id}/handoff/jobs/{job_id}/diff",
    response_model=HandoffDiffResponse,
)
async def get_handoff_job_diff(
    conversation_id: str,
    job_id: str,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    job_repo: HandoffJobRepository = Depends(get_handoff_job_repo),
):
    """A finished handoff's result diff — the change set for the local apply (P2e / e3).

    Compares the team's result snapshot against the base it ran on and returns the
    per-file change set (added / modified / deleted) the desktop replays onto the
    user's local files; each entry carries the base hash for the client's three-way
    conflict check (clean / already-applied / conflict). 404 if the conversation is
    not owned or the job is unknown / from another source conversation; 409 while the
    job has not succeeded yet (no result to diff).
    """
    await _require_owned_conversation(conversation_id, user.user_id, conv_repo)
    job = await job_repo.get_by_id(job_id, user_id=user.user_id)
    if job is None or job.source_conversation_id != conversation_id:
        raise NotFoundError("交接任务不存在")
    if job.status != "succeeded" or not job.result_snapshot_id:
        raise ConflictError("交接任务尚未产出结果")
    try:
        changes = await compute_handoff_diff(
            user_id=user.user_id,
            source_folder_id=None,
            source_conversation_id=conversation_id,
            base_snapshot_id=job.base_snapshot_id,
            job_conversation_id=job.job_conversation_id,
            result_snapshot_id=job.result_snapshot_id,
        )
    except SnapshotNotFound as e:
        raise NotFoundError("交接快照不存在") from e
    data = [HandoffFileChange.model_validate(c) for c in changes]
    return HandoffDiffResponse(
        job_id=job.id,
        data=data,
        total=len(data),
        added=sum(1 for c in data if c.change_type == "added"),
        modified=sum(1 for c in data if c.change_type == "modified"),
        deleted=sum(1 for c in data if c.change_type == "deleted"),
    )


async def _run_apply(
    *,
    user_id: str,
    source_folder_id: str | None,
    source_conversation_id: str,
    job_id: str,
    job_conversation_id: str,
    base_snapshot_id: str,
    result_snapshot_id: str,
    binding: LocalBinding,
    selections: list[ApplySelection],
    sink: EventSink,
) -> None:
    """Drive a handoff result apply to completion over its SSE sink (P2e / e3).

    Builds the desktop-backed ``LocalWorkspace`` over this stream, then replays the
    accepted changes onto the user's machine (WRITE_BYTES / DELETE the bound desktop
    fulfils). On success a ``handoff_apply_done`` carrying the per-file outcomes is
    emitted before the stream closes; a missing snapshot or any failure surfaces as
    an inline ``error`` event (never an unhandled crash on this detached task).
    """
    try:
        backend = build_workspace(
            user_id=user_id,
            folder_id=source_folder_id,
            conversation_id=source_conversation_id,
            sink=sink,
            local_binding=binding,
        )
        outcomes = await apply_handoff(
            backend=backend,
            user_id=user_id,
            source_folder_id=source_folder_id,
            source_conversation_id=source_conversation_id,
            base_snapshot_id=base_snapshot_id,
            job_conversation_id=job_conversation_id,
            result_snapshot_id=result_snapshot_id,
            selections=selections,
        )
        sink.emit(
            handoff_apply_done(
                job_id=job_id,
                conversation_id=source_conversation_id,
                results=[o.to_dict() for o in outcomes],
            )
        )
    except SnapshotNotFound as e:
        logger.warning(
            "handoff.apply_snapshot_missing",
            conversation_id=source_conversation_id,
            error=str(e),
        )
        sink.emit(error_event(ErrorCode.HANDOFF_SNAPSHOT_NOT_FOUND, str(e)))
    except Exception as e:
        logger.warning(
            "handoff.apply_failed",
            conversation_id=source_conversation_id,
            error=str(e),
        )
        sink.emit(error_event(ErrorCode.HANDOFF_APPLY_FAILED, str(e)))
    finally:
        if not sink._closed:
            sink.close()


@router.post("/{conversation_id}/handoff/jobs/{job_id}/apply")
async def apply_handoff_job(
    conversation_id: str,
    job_id: str,
    body: ApplyHandoffRequest,
    user: AuthUser,
    conv_repo: ConversationRepository = Depends(get_conversation_repo),
    job_repo: HandoffJobRepository = Depends(get_handoff_job_repo),
):
    """Apply a finished handoff's selected changes back to the local workspace (P2e / e3).

    The last leg of the 本地→云 round trip: the user's per-file decisions (take cloud /
    keep local, with the locally-observed hash) are replayed onto their machine over
    the channel. Streams SSE: ``workspace_op_required`` (WRITE_BYTES / DELETE) the
    bound desktop fulfils, then a ``handoff_apply_done`` with the per-file outcomes.
    The conflict gate is server-authoritative — a file that diverged locally since the
    base is refused (status ``conflict``) unless its selection ``force``\\s it.

    404 if the conversation is not owned or the job is unknown / from another source;
    409 while the job has not succeeded yet; 422 when the conversation is not in local
    mode (nothing local to apply onto).
    """
    conv = await _get_owned_conversation(conversation_id, user.user_id, conv_repo)
    job = await job_repo.get_by_id(job_id, user_id=user.user_id)
    if job is None or job.source_conversation_id != conversation_id:
        raise NotFoundError("交接任务不存在")
    if job.status != "succeeded" or not job.result_snapshot_id:
        raise ConflictError("交接任务尚未产出结果")

    binding = resolve_conversation_local_binding(
        local_root_id=conv.local_root_id,
        local_subpath=conv.local_subpath,
        label="workspace",
    )
    if binding is None:
        raise ValidationError("该对话不是本地模式")

    selections = [
        ApplySelection(path=s.path, decision=s.decision, local_sha=s.local_sha, force=s.force)
        for s in body.selections
    ]
    sink = EventSink()
    task = asyncio.create_task(
        _run_apply(
            user_id=user.user_id,
            source_folder_id=None,
            source_conversation_id=conversation_id,
            job_id=job.id,
            job_conversation_id=job.job_conversation_id,
            base_snapshot_id=job.base_snapshot_id,
            result_snapshot_id=job.result_snapshot_id,
            binding=binding,
            selections=selections,
            sink=sink,
        )
    )
    return sse_response(sink, producer=task)
