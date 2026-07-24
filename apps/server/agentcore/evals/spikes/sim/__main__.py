"""CLI entry for AI Town MVP spikes (SPIKE-02/03/06).

Usage (from apps/server):
  uv run python -m agentcore.evals.spikes.sim spike03
  uv run python -m agentcore.evals.spikes.sim spike06 [--ticks 8] [--agents 4]
  uv run python -m agentcore.evals.spikes.sim spike02
  uv run python -m agentcore.evals.spikes.sim all
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

from agentcore.core.log_context import bind_log_context
from agentcore.db.base import async_session_factory
from agentcore.simulation.llm import SimLlmNotConfigured, resolve_text_mode

from .harness import (
    TickResult,
    TranscriptLine,
    build_real_llm_async,
    format_transcript_line,
    run_agent_tick,
    tick_to_transcript,
)
from .personas import PERSONAS, Persona, seed_world
from .world import WorldState

_OUTPUT_DIR = Path(__file__).parent / "output"


async def _probe_llm() -> tuple[bool, str]:
    try:
        import httpx
        from sqlalchemy import text

        async with async_session_factory() as session:
            from agentcore.simulation.llm import resolve_sim_model_config

            user_id: str | None = None
            row = await session.execute(text("SELECT user_id FROM user_llm_providers LIMIT 1"))
            uid = row.scalar()
            if uid is not None:
                user_id = str(uid)
            cfg = await resolve_sim_model_config(session, user_id)
        async with httpx.AsyncClient(timeout=30) as c:
            r = await c.post(
                f"{cfg.base_url.rstrip('/')}/chat/completions",
                headers={"Authorization": f"Bearer {cfg.api_key}"},
                json={
                    "model": cfg.model,
                    "messages": [{"role": "user", "content": "ping"}],
                    "max_tokens": 5,
                },
            )
        if r.status_code == 200:
            return True, f"ok ({cfg.model} via {cfg.source})"
        return False, f"HTTP {r.status_code}: {r.text[:200]}"
    except SimLlmNotConfigured as e:
        return False, str(e)
    except Exception as e:
        return False, str(e)


async def _resolve_spike_llm():
    from sqlalchemy import text

    async with async_session_factory() as session:
        row = await session.execute(text("SELECT user_id FROM user_llm_providers LIMIT 1"))
        uid = row.scalar()
        user_id = str(uid) if uid is not None else None
        return await build_real_llm_async(session, user_id)


async def cmd_spike03() -> int:
    print("=== SPIKE-03: bypass conversation → react_loop (mock) ===\n")
    from .mock_provider import mock_move_then_summarize
    from .personas import persona_by_id, seed_world

    world = seed_world()
    result = await run_agent_tick(
        world=world, persona=persona_by_id("lin"), llm=mock_move_then_summarize()
    )
    moved = world.agents["lin"].location == "市场"
    print(f"error: {result.error}")
    print(f"tool_calls: {result.tool_calls}")
    print(f"content: {result.content!r}")
    print(f"location after tick: {world.agents['lin'].location}")
    print(f"rounds: {result.rounds}, latency_ms: {result.latency_ms}")
    print(f"\nSPIKE-03 mock: {'PASS' if moved and result.error is None else 'FAIL'}")
    return 0 if moved and result.error is None else 1


async def _run_simulation(
    *,
    personas: tuple[Persona, ...],
    ticks: int,
    llm,
    turn_model: str,
    text_mode: bool | None,
    label: str,
) -> tuple[list[TranscriptLine], list[TickResult], WorldState]:
    world = seed_world(personas)
    lines: list[TranscriptLine] = []
    results: list[TickResult] = []
    for _ in range(ticks):
        world.advance_clock()
        print(f"  tick {world.tick} ({world.hour:02d}:00)...", flush=True)
        for persona in personas:
            result = await run_agent_tick(
                world=world,
                persona=persona,
                llm=llm,
                text_mode=text_mode,
                turn_model=turn_model,
            )
            results.append(result)
            lines.append(tick_to_transcript(world, persona, result))
            if result.error:
                print(f"    ! {persona.name}: {result.error}")
    return lines, results, world


async def cmd_spike06(*, ticks: int, agent_count: int, text_mode: bool | None) -> int:
    auto_label = "auto (DeepSeek→tools, else JSON)"
    mode_label = (
        "text-JSON fallback"
        if text_mode is True
        else "tool-calling"
        if text_mode is False
        else auto_label
    )
    print(f"=== SPIKE-06: emergence smoke (real LLM, {mode_label}) ===\n")
    ok, reason = await _probe_llm()
    if not ok:
        print(f"BLOCKED: real LLM unavailable — {reason}")
        print("SPIKE-06 需配置 DeepSeek（PLATFORM_* / BYOK / EVAL_DEEPSEEK_API_KEY）后再跑。")
        return 2
    print(f"LLM probe: {reason}\n")
    personas = PERSONAS[:agent_count]
    llm, llm_cfg = await _resolve_spike_llm()
    effective_text_mode = resolve_text_mode(llm_cfg.base_url, override=text_mode)
    print(
        f"Resolved: model={llm_cfg.model} base={llm_cfg.base_url} source={llm_cfg.source} "
        f"text_mode={effective_text_mode}\n"
    )
    t0 = time.monotonic()
    lines, results, world = await _run_simulation(
        personas=personas,
        ticks=ticks,
        llm=llm,
        turn_model=llm_cfg.model,
        text_mode=effective_text_mode,
        label="spike06",
    )
    elapsed = time.monotonic() - t0
    total_cost = sum(r.cost_usd for r in results)
    total_tokens = sum(r.usage.get("input", 0) + r.usage.get("output", 0) for r in results)

    _OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    out_txt = _OUTPUT_DIR / "spike06_transcript.txt"
    out_json = _OUTPUT_DIR / "spike06_transcript.json"
    text = "\n\n".join(format_transcript_line(ln) for ln in lines)
    text += "\n\n---\n世界事件日志:\n" + "\n".join(world.event_log)
    out_txt.write_text(text, encoding="utf-8")
    out_json.write_text(
        json.dumps(
            {
                "agents": agent_count,
                "ticks": ticks,
                "model": llm_cfg.model,
                "llm_source": llm_cfg.source,
                "text_mode": effective_text_mode,
                "elapsed_s": round(elapsed, 1),
                "total_cost_usd": round(total_cost, 4),
                "total_tokens": total_tokens,
                "lines": [ln.__dict__ for ln in lines],
                "events": world.event_log,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )

    print(f"\nTranscript: {out_txt}")
    print(f"Elapsed: {elapsed:.1f}s | tokens: {total_tokens} | cost: ${total_cost:.4f}")
    print("\n--- 样本摘要（每角色首尾 tick）---")
    by_agent: dict[str, list[TranscriptLine]] = {}
    for ln in lines:
        by_agent.setdefault(ln.agent_id, []).append(ln)
    for pid, agent_lines in by_agent.items():
        print(f"\n▸ {agent_lines[0].agent_name}")
        for ln in [agent_lines[0], agent_lines[-1]]:
            print(f"  {format_transcript_line(ln)}")
    return 0


async def cmd_spike02() -> int:
    print("=== SPIKE-02: concurrency + latency probe ===\n")
    from .mock_provider import ScriptedProvider, content_chunk, tool_chunk

    # --- Part A: mock 12 agents parallel, single tick ---
    async def _mock_one(agent_id: str) -> int:
        world = seed_world(persona for persona in PERSONAS if persona.agent_id == agent_id)
        world.tick = 1
        persona = next(p for p in PERSONAS if p.agent_id == agent_id)
        provider = ScriptedProvider(
            [
                [tool_chunk("stay_here", f'{{"activity":"mock-{agent_id}","reason":"probe"}}')],
                [content_chunk(f"ok-{agent_id}")],
            ]
        )
        t0 = time.monotonic()
        await run_agent_tick(world=world, persona=persona, llm=provider)
        return int((time.monotonic() - t0) * 1000)

    sem = asyncio.Semaphore(6)
    agent_ids = [p.agent_id for p in PERSONAS] + ["lin", "chen", "zhao", "wang", "liu", "lin"]

    async def _guarded(aid: str) -> int:
        async with sem:
            return await _mock_one(aid)

    t0 = time.monotonic()
    mock_latencies = await asyncio.gather(*[_guarded(a) for a in agent_ids[:12]])
    mock_wall = time.monotonic() - t0
    print(f"Mock 12-agent × 1 tick (max_parallel=6): wall={mock_wall:.2f}s")
    print(f"  per-agent latency ms: min={min(mock_latencies)} max={max(mock_latencies)}")

    # --- Part B: real LLM 3 agents × 2 ticks ---
    ok, reason = await _probe_llm()
    if not ok:
        print(f"\nReal LLM part BLOCKED: {reason}")
        print("推荐 max_parallel=4~6（mock 基线已测）")
        return 0

    personas = PERSONAS[:3]
    llm, llm_cfg = await _resolve_spike_llm()
    effective_text_mode = resolve_text_mode(llm_cfg.base_url, override=True)
    t0 = time.monotonic()
    lines, results, _ = await _run_simulation(
        personas=personas,
        ticks=2,
        llm=llm,
        turn_model=llm_cfg.model,
        text_mode=effective_text_mode,
        label="spike02",
    )
    elapsed = time.monotonic() - t0
    per_decision = [r.latency_ms for r in results]
    total_cost = sum(r.cost_usd for r in results)
    avg = sum(per_decision) / len(per_decision) if per_decision else 0
    print(f"\nReal 3-agent × 2 tick: wall={elapsed:.1f}s")
    print(f"  per-decision latency ms: avg={avg:.0f} min={min(per_decision)} max={max(per_decision)}")
    print(f"  total cost: ${total_cost:.4f}")
    print(f"推荐 max_parallel=3~4（单决策 ~{avg / 1000:.0f}s 量级）")
    return 0


def main(argv: list[str] | None = None) -> int:
    # Synthetic batch traffic — filterable in logs/dev.jsonl (absence of ``traffic`` = real).
    bind_log_context(traffic="eval")
    parser = argparse.ArgumentParser(description="AI Town MVP spikes")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("spike03", help="SPIKE-03 mock smoke")
    p06 = sub.add_parser("spike06", help="SPIKE-06 emergence (real LLM)")
    p06.add_argument("--ticks", type=int, default=8)
    p06.add_argument("--agents", type=int, default=4, choices=range(1, 6))
    p06.add_argument(
        "--text-mode",
        action="store_true",
        help="Force JSON text actions (bypass native tool calling)",
    )
    p06.add_argument("--tool-mode", action="store_true", help="Force function-calling path")
    sub.add_parser("spike02", help="SPIKE-02 concurrency probe")
    sub.add_parser("all", help="Run spike03 + spike06 + spike02")
    args = parser.parse_args(argv)

    if args.cmd == "spike03":
        return asyncio.run(cmd_spike03())
    if args.cmd == "spike06":
        if getattr(args, "tool_mode", False) and getattr(args, "text_mode", False):
            print("Cannot use --text-mode and --tool-mode together")
            return 1
        text_mode: bool | None = None
        if getattr(args, "tool_mode", False):
            text_mode = False
        elif getattr(args, "text_mode", False):
            text_mode = True
        return asyncio.run(cmd_spike06(ticks=args.ticks, agent_count=args.agents, text_mode=text_mode))
    if args.cmd == "spike02":
        return asyncio.run(cmd_spike02())
    if args.cmd == "all":
        rc = asyncio.run(cmd_spike03())
        if rc:
            return rc
        rc = asyncio.run(cmd_spike06(ticks=8, agent_count=4, text_mode=None))
        if rc == 2:
            return 0  # blocked is ok for all
        if rc:
            return rc
        return asyncio.run(cmd_spike02())
    return 1


if __name__ == "__main__":
    sys.exit(main())
