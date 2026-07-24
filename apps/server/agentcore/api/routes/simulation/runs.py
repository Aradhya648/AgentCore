"""Simulation REST API (M1): create run, advance tick, SSE stream, tick readback."""

from __future__ import annotations

from collections.abc import AsyncIterator

from fastapi import APIRouter, Depends, Query
from starlette.responses import StreamingResponse

from agentcore.api.dependencies import AuthUser, get_simulation_repo
from agentcore.api.schemas.simulation import (
    AdvanceTickResponse,
    CreateSimulationRunRequest,
    InjectSimulationEventRequest,
    InjectSimulationEventResponse,
    PatchSimulationAgentRequest,
    PatchSimulationAgentResponse,
    SimTickFrameResponse,
    SimulationRunManifestResponse,
    SimulationRunMetricsResponse,
    SimulationRunStatusResponse,
    SimulationRunSummary,
)
from agentcore.api.sse import _format_sse, sse_attach_response
from agentcore.core.errors import NotFoundError, ValidationError
from agentcore.db.repositories import SimulationRepository
from agentcore.simulation.service import SimulationService, simulation_enabled
from agentcore.simulation.stream_registry import default_sim_stream_registry

router = APIRouter(prefix="/simulation", tags=["simulation"])


def _require_simulation_enabled() -> None:
    if not simulation_enabled():
        raise NotFoundError("模拟功能未启用")


def _service(repo: SimulationRepository) -> SimulationService:
    return SimulationService(repo, stream_registry=default_sim_stream_registry)


@router.post("/runs", response_model=SimulationRunSummary, status_code=201)
async def create_run(
    body: CreateSimulationRunRequest,
    user: AuthUser,
    repo: SimulationRepository = Depends(get_simulation_repo),
):
    _require_simulation_enabled()
    run = await _service(repo).create_run(
        user_id=user.user_id,
        scenario=body.scenario,
        seed=body.seed,
        scripted=body.scripted,
        manifest=body.manifest,
    )
    return SimulationRunSummary.model_validate(run)


@router.post("/runs/{run_id}/tick", response_model=AdvanceTickResponse)
async def advance_tick(
    run_id: str,
    user: AuthUser,
    repo: SimulationRepository = Depends(get_simulation_repo),
):
    _require_simulation_enabled()
    service = _service(repo)
    try:
        snapshot = await service.advance_tick(run_id, user_id=user.user_id)
    except KeyError:
        raise NotFoundError("模拟 run 不存在") from None
    except ValidationError as e:
        raise ValidationError(str(e)) from None
    return AdvanceTickResponse(run_id=run_id, snapshot=snapshot)


@router.post("/runs/{run_id}/pause", response_model=SimulationRunStatusResponse)
async def pause_run(
    run_id: str,
    user: AuthUser,
    repo: SimulationRepository = Depends(get_simulation_repo),
):
    _require_simulation_enabled()
    service = _service(repo)
    try:
        await service.pause_run(run_id, user_id=user.user_id)
    except KeyError:
        raise NotFoundError("模拟 run 不存在") from None
    except ValidationError as e:
        raise ValidationError(str(e)) from None
    run = await repo.get_run(run_id, user_id=user.user_id)
    assert run is not None
    return SimulationRunStatusResponse(
        run_id=run_id, status=run.status, current_tick=run.current_tick
    )


@router.post("/runs/{run_id}/resume", response_model=SimulationRunStatusResponse)
async def resume_run(
    run_id: str,
    user: AuthUser,
    repo: SimulationRepository = Depends(get_simulation_repo),
):
    _require_simulation_enabled()
    service = _service(repo)
    try:
        await service.resume_run(run_id, user_id=user.user_id)
    except KeyError:
        raise NotFoundError("模拟 run 不存在") from None
    except ValidationError as e:
        raise ValidationError(str(e)) from None
    run = await repo.get_run(run_id, user_id=user.user_id)
    assert run is not None
    return SimulationRunStatusResponse(
        run_id=run_id, status=run.status, current_tick=run.current_tick
    )


@router.get("/runs/{run_id}/ticks/{tick_number}", response_model=SimTickFrameResponse)
async def get_tick_frame(
    run_id: str,
    tick_number: int,
    user: AuthUser,
    repo: SimulationRepository = Depends(get_simulation_repo),
):
    _require_simulation_enabled()
    if tick_number < 1:
        raise ValidationError("tick_number 必须 >= 1")
    service = _service(repo)
    snapshot = await service.get_tick_snapshot(run_id, tick_number, user_id=user.user_id)
    if snapshot is None:
        raise NotFoundError("tick 不存在或超出 run 范围")
    return SimTickFrameResponse(run_id=run_id, tick_number=tick_number, snapshot=snapshot)


@router.get("/runs/{run_id}/metrics", response_model=SimulationRunMetricsResponse)
async def get_run_metrics(
    run_id: str,
    user: AuthUser,
    repo: SimulationRepository = Depends(get_simulation_repo),
):
    _require_simulation_enabled()
    service = _service(repo)
    metrics = await service.list_run_metrics(run_id, user_id=user.user_id)
    if metrics is None:
        raise NotFoundError("模拟 run 不存在")
    return SimulationRunMetricsResponse(run_id=run_id, metrics=metrics)


@router.get("/runs/{run_id}/manifest", response_model=SimulationRunManifestResponse)
async def get_run_manifest(
    run_id: str,
    user: AuthUser,
    repo: SimulationRepository = Depends(get_simulation_repo),
):
    _require_simulation_enabled()
    service = _service(repo)
    manifest = await service.get_run_manifest(run_id, user_id=user.user_id)
    if manifest is None:
        raise NotFoundError("模拟 run 或 manifest 不存在")
    return SimulationRunManifestResponse(run_id=run_id, manifest=manifest)



@router.get("/runs/{run_id}/replay")
async def replay_run(
    run_id: str,
    user: AuthUser,
    from_tick: int = Query(..., alias="from", ge=1),
    to_tick: int = Query(..., alias="to", ge=1),
    repo: SimulationRepository = Depends(get_simulation_repo),
):
    _require_simulation_enabled()
    service = _service(repo)
    try:
        events = await service.replay_ticks(
            run_id,
            user_id=user.user_id,
            from_tick=from_tick,
            to_tick=to_tick,
        )
    except KeyError:
        raise NotFoundError("模拟 run 不存在") from None
    except ValidationError as e:
        raise ValidationError(str(e)) from None

    async def _generator() -> AsyncIterator[str]:
        for event in events:
            yield _format_sse(event)

    return StreamingResponse(
        _generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/runs/{run_id}/stream")
async def stream_run(
    run_id: str,
    user: AuthUser,
    repo: SimulationRepository = Depends(get_simulation_repo),
):
    _require_simulation_enabled()
    run = await repo.get_run(run_id, user_id=user.user_id)
    if run is None:
        raise NotFoundError("模拟 run 不存在")
    sink = await default_sim_stream_registry.get_or_create(run_id)
    return sse_attach_response(sink)


@router.post("/runs/{run_id}/inject", response_model=InjectSimulationEventResponse, status_code=202)
async def inject_event(
    run_id: str,
    body: InjectSimulationEventRequest,
    user: AuthUser,
    repo: SimulationRepository = Depends(get_simulation_repo),
):
    _require_simulation_enabled()
    service = _service(repo)
    try:
        event = await service.inject_event(
            run_id,
            user_id=user.user_id,
            event_type=body.event_type,
            payload=body.payload,
        )
    except KeyError:
        raise NotFoundError("模拟 run 不存在") from None
    run = await repo.get_run(run_id, user_id=user.user_id)
    assert run is not None
    return InjectSimulationEventResponse(
        run_id=run_id,
        event_id=event.event_id,
        event_type=event.event_type,
        title=event.title,
        queued_for_tick=run.current_tick + 1,
    )


@router.patch("/runs/{run_id}/agents/{agent_id}", response_model=PatchSimulationAgentResponse)
async def patch_agent(
    run_id: str,
    agent_id: str,
    body: PatchSimulationAgentRequest,
    user: AuthUser,
    repo: SimulationRepository = Depends(get_simulation_repo),
):
    _require_simulation_enabled()
    service = _service(repo)
    try:
        state = await service.patch_agent(
            run_id,
            agent_id,
            user_id=user.user_id,
            mood=body.mood,
            goal=body.goal,
            money=body.money,
        )
    except KeyError:
        raise NotFoundError("模拟 run 或居民不存在") from None
    except ValidationError as e:
        raise ValidationError(str(e)) from None
    return PatchSimulationAgentResponse(run_id=run_id, agent_id=agent_id, state=state)
