"""harness：把一个黄金用例跑过**真实运行路径**，归一化成可断言的 :class:`TurnOutcome`.

零侵入（评估体系 §四）：只消费现有运行入口的返回值与 ``EventSink`` 事件，不改引擎/管线
一行——
- ``single`` 路径 → :func:`agentcore.runtime.engine.react_loop`（轻、快，测工具/引用最准）；
- ``team`` 路径   → :func:`agentcore.runtime.pipeline.run_chat_pipeline`（拿 ``runs`` 判委派、
  ``cost_runs`` 算成本），强制 ``approvals_enabled=False`` 关掉 ask_user/plan_review 挂起，
  评测绝不空等超时。

过程事实（工具调用、委派角色）由 :class:`~agentcore.evals.recording_sink.RecordingSink`
（在现有 ``EventSink`` 上挂钩）截获。
真实 DeepSeek key 经 :func:`_eval_credentials` 从 eval 专用环境变量读（BYOK 下平台 key 为空，
见 §十三）；单测注入脚本化假 provider（``EvalHarness(provider=...)``），零成本验证 harness 本身。

``plan_only=True``：经 :func:`~agentcore.runtime.plan_only.use_plan_only` 打开默认关闭的
delegate/debate 干跑开关——真实规划路径照走，首个 ``run_plan`` 后 HANDOFF 收束；CEO
``max_rounds`` 压到 :data:`~agentcore.runtime.plan_only.PLAN_ONLY_CEO_MAX_ROUNDS` 防 solo
搜网页空转。
"""

from __future__ import annotations

import os
import shutil
import tempfile
import time
from dataclasses import replace
from pathlib import Path

from agentcore.config import settings
from agentcore.core.log_context import log_context, new_trace_id
from agentcore.core.logging import get_logger
from agentcore.core.types import new_id
from agentcore.evals.eval_modes import KNOWN_MODELS, resolve_profile_set
from agentcore.evals.prompt_profiles import resolve_prompt_profile
from agentcore.evals.recording_sink import RecordingSink
from agentcore.evals.types import (
    EvalCase,
    EvalConfigError,
    TurnOutcome,
    artifacts_from_tool_calls,
)
from agentcore.llm.factory import build_provider
from agentcore.llm.pricing import NANO_PER_CNY, calculate_cost
from agentcore.llm.profiles import ProfileParams, TurnProfiles
from agentcore.llm.provider.protocol import LLMMessage, TokenUsage
from agentcore.llm.resolve import LLMCredentials
from agentcore.runtime.costing import aggregate_cost
from agentcore.runtime.engine import react_loop
from agentcore.runtime.events import FinishReason
from agentcore.runtime.pipeline import run_chat_pipeline
from agentcore.runtime.plan_only import PLAN_ONLY_CEO_MAX_ROUNDS, use_plan_only
from agentcore.runtime.prompt_profile import use_profile
from agentcore.tools.builtin import build_ceo_tool_registry, build_worker_registry
from agentcore.tools.protocol import ToolContext
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace

logger = get_logger(__name__)

# Eval exercises the FULL model catalog (incl. Pro), decoupled from user BYOK model
# selection. Eval must still resolve ``quality`` → Pro to compare Flash-vs-Pro CEO and
# run the Pro judge — see ``evals/eval_modes.py``.
_EVAL_CEILING = frozenset(KNOWN_MODELS)

# eval 运行的固定隔离身份：独立 user_id（避免读到真实用户的记忆/配额），workspace 由
# fixture 或临时目录提供。记忆换底 documents 表后 user_id 列是 UUID 型（asyncpg 强转），
# 故必须是 UUID 形（固定值=永不与真实用户 uuid4 撞车）；eval 流量标识走 traffic="eval"，
# 不依赖本值。"e7a1" ≈ "eval"。
_EVAL_USER_ID = "e7a10000-0000-4000-8000-000000000000"
_DEFAULT_FIXTURES_DIR = Path(__file__).parent / "fixtures"


def _clamp_ceo_rounds(profiles: TurnProfiles, max_rounds: int) -> TurnProfiles:
    """Return a TurnProfiles duck that caps the CEO (``chat``) max_rounds only."""

    class _Clamped(TurnProfiles):  # type: ignore[misc,valid-type]
        def get(self, name: str) -> ProfileParams:  # noqa: A003
            p = TurnProfiles.get(self, name)
            if name == "chat":
                return replace(p, max_rounds=max_rounds)
            return p

    return _Clamped(model=profiles.model, model_overrides=dict(profiles.model_overrides))


def _eval_credentials() -> LLMCredentials:
    """eval 的 DeepSeek / 平台凭据：优先 eval 专用环境变量，否则显式平台凭据.

    BYOK 内测下平台 ``platform_api_key`` 多为空 → 真跑必须自带 ``EVAL_DEEPSEEK_API_KEY``
    （建议配低额度账号 + nightly 限次）。不再经 ``build_provider(None)`` 静默回落。
    单测走注入的假 provider，不读这里。
    """
    from agentcore.llm.resolve import platform_llm_credentials

    key = os.environ.get("EVAL_DEEPSEEK_API_KEY", "").strip()
    if key:
        base = (
            os.environ.get("EVAL_DEEPSEEK_BASE_URL", "").strip()
            or settings.platform_base_url
        )
        model = (
            os.environ.get("EVAL_DEEPSEEK_MODEL", "").strip() or settings.platform_model
        )
        return LLMCredentials(api_key=key, base_url=base, default_model=model)
    plat = platform_llm_credentials()
    if plat is None:
        raise RuntimeError(
            "eval needs EVAL_DEEPSEEK_API_KEY or a configured PLATFORM_API_KEY "
            "(build_provider no longer silent-falls back)"
        )
    return plat


def _history_messages(history: list[dict]) -> list[LLMMessage]:
    """把用例的 ``history``（``[{role, content}]``）转成 ``react_loop`` 吃的 LLMMessage。"""
    return [
        LLMMessage(role=m.get("role", "user"), content=m.get("content", ""))
        for m in (history or [])
    ]


def _ms(t0: float) -> int:
    return int((time.monotonic() - t0) * 1000)


def single_outcome(
    content: str,
    usage: TokenUsage,
    rounds: int,
    *,
    profile: ProfileParams,
    model: str,
    sink: RecordingSink,
    citations: list[dict],
    latency_ms: int,
    finish_override: FinishReason | None = None,
    workspace_root: str | None = None,
    reference_root: str | None = None,
) -> TurnOutcome:
    """把 ``react_loop`` 的返回值 + sink 截获的事实归一化成 :class:`TurnOutcome`.

    ``react_loop`` 的四元组不带 finish_reason，但 B2 收敛治理会把非默认终态经
    ``finish_override_sink`` 抬出来：``DEGRADED``（空响应即便 fallback 后仍空）/
    ``UNPRODUCTIVE``（连续全失败无正文早停）。有 ``finish_override`` 就用它（评估据此能
    断言降级 / 早停、与 team 路径口径一致），否则镜像 pipeline 按轮数推导（rounds 达上限即
    ``max_rounds``，否则 ``end_turn``）。成本用 ``runtime/costing`` 的定价按 usage+model
    现算（``react_loop`` 不回 cost）。纯函数，便于单测。
    """
    if finish_override is not None:
        finish = finish_override.value
    else:
        finish = "end_turn" if rounds < profile.max_rounds else "max_rounds"
    cost_nano = calculate_cost(model, usage, billing_mode="platform").total
    tool_calls = list(sink.tool_calls)
    return TurnOutcome(
        content=content or "",
        finish_reason=finish,
        rounds=rounds,
        tool_calls=tool_calls,
        citations=list(citations),
        delegated=False,
        roster=[],
        usage=usage.as_dict(),
        cost_usd=cost_nano / NANO_PER_CNY,
        latency_ms=latency_ms,
        plan_runs=list(sink.plan_runs),
        plan_type=sink.plan_type,
        collab_interactions=dict(sink.collab_interactions),
        artifacts=artifacts_from_tool_calls(tool_calls),
        workspace_root=workspace_root,
        reference_root=reference_root,
    )


def team_outcome(
    result: dict,
    sink: RecordingSink,
    *,
    latency_ms: int,
    workspace_root: str | None = None,
    reference_root: str | None = None,
) -> TurnOutcome:
    """把 ``run_chat_pipeline`` 的返回 dict + sink 截获的 roster 归一化成 :class:`TurnOutcome`.

    ``delegated`` 以 roster 里是否出现**非 CEO 角色**为准（roster 来自 ``run_plan`` 的委派
    计划）。**不能**用 ``bool(runs)``——实测发现 CEO 直接作答 / 反问澄清（rounds=1、零
    ``delegate`` 调用、roster 空）时 ``runs`` 仍非空（含 CEO 自身的 run 记录），会把「零
    编排的直接回答」误判为委派、令 ``Delegated``/``NotDelegated`` 失真。成本读 ``cost_runs``
    经 ``aggregate_cost`` 求和（worker 与 captain 可能不同档，只能加各自已定价的行）。错误
    路径返回的 dict 缺多数键，故全部用 ``.get`` 带默认。纯函数，便于单测。
    """
    finish = result.get("finish_reason")
    finish_str = finish.value if hasattr(finish, "value") else str(finish or "error")
    cost_runs = result.get("cost_runs") or []
    cost_nano = int(aggregate_cost(cost_runs).get("total", 0)) if cost_runs else 0
    usage = {
        "input": int(result.get("input_tokens", 0)),
        "output": int(result.get("output_tokens", 0)),
        "reasoning": int(result.get("reasoning_tokens", 0)),
    }
    tool_calls = list(sink.tool_calls)
    return TurnOutcome(
        content=result.get("content", "") or "",
        finish_reason=finish_str,
        rounds=int(result.get("rounds", 0)),
        tool_calls=tool_calls,
        citations=list(result.get("citations") or []),
        delegated=any(role != "CEO" for role in sink.roster),
        roster=list(sink.roster),
        usage=usage,
        cost_usd=cost_nano / NANO_PER_CNY,
        latency_ms=latency_ms,
        error=result.get("error"),
        plan_runs=list(sink.plan_runs),
        plan_type=sink.plan_type,
        collab_interactions=dict(sink.collab_interactions),
        artifacts=artifacts_from_tool_calls(tool_calls),
        workspace_root=workspace_root,
        reference_root=reference_root,
    )


class EvalHarness:
    """默认 harness：实现 :class:`~agentcore.evals.types.Harness` 协议。

    ``provider`` 注入仅作用于 **single 路径**（``react_loop`` 直接收 ``llm=``）——单测据此
    用脚本化假 provider 零成本验证 harness。team 路径走 ``run_chat_pipeline``，其内部自建
    provider（无注入缝，遵守零侵入），故 team 的零 LLM 自测改为直测 ``RecordingSink`` 事件
    还原 + :func:`team_outcome` 纯映射（见 tests/test_evals_smoke.py），真模型留给 nightly。

    ``plan_only``：只评 CEO 规划形状——打开 runtime plan-only 开关并压紧 CEO 轮次预算。
    """

    def __init__(
        self,
        *,
        provider=None,
        fixtures_dir: Path | None = None,
        plan_only: bool = False,
    ) -> None:
        self._provider = provider
        self._fixtures_dir = fixtures_dir or _DEFAULT_FIXTURES_DIR
        self._plan_only = plan_only

    async def run_case(self, case: EvalCase) -> TurnOutcome:
        sink = RecordingSink()
        ws_root = self._fixture_root(case)
        backend = ServerWorkspace(root=ws_root, sandbox=SubprocessSandbox())
        profiles = resolve_profile_set(case.mode, custom_modes={}, ceiling=_EVAL_CEILING)
        if self._plan_only:
            profiles = _clamp_ceo_rounds(profiles, PLAN_ONLY_CEO_MAX_ROUNDS)
        # 方向①：在本例运行期激活声明的 prompt 变体（None=基线/恒等）。装配函数（深在
        # run_chat_pipeline 内）经 contextvar 就地咨询，故无需改 pipeline / engine 签名；退出
        # use_profile 必复位，变体不泄漏到本例之外。
        prompt_profile = resolve_prompt_profile(case.prompt_profile)
        t0 = time.monotonic()
        # Bind a correlation context for this case the way the prod turn boundary does
        # (turn_runner / local_turn): evals drive react_loop / run_chat_pipeline directly,
        # bypassing turn_runner, so without this the engine's convergence logs (loop_nudge /
        # loop_finalize / max_rounds_exhausted) would carry NO trace_id — leaving them
        # un-correlatable and skewing offline log_stats. ``case`` is the eval analogue of
        # turn_id (already used as the failure-log key below). Evals never emit
        # chat.turn_complete, so these traces stay correctly excluded from the 空转率 turn set.
        ws = str(ws_root)
        with (
            log_context(trace_id=new_trace_id(), user_id=_EVAL_USER_ID, case=case.id),
            use_profile(prompt_profile),
            use_plan_only(self._plan_only),
        ):
            try:
                if case.path == "single":
                    return await self._run_single(
                        case, backend, profiles, sink, t0, workspace_root=ws
                    )
                return await self._run_team(
                    case, backend, profiles, sink, t0, workspace_root=ws
                )
            except Exception as e:  # react_loop/pipeline 失败 → error 态（不让一例炸掉整套）
                logger.error("evals.run_case_failed", case=case.id, error=str(e), exc_info=True)
                tool_calls = list(sink.tool_calls)
                return TurnOutcome(
                    content="",
                    finish_reason="error",
                    rounds=0,
                    tool_calls=tool_calls,
                    latency_ms=_ms(t0),
                    error=str(e),
                    plan_runs=list(sink.plan_runs),
                    plan_type=sink.plan_type,
                    collab_interactions=dict(sink.collab_interactions),
                    artifacts=artifacts_from_tool_calls(tool_calls),
                    workspace_root=ws,
                )

    async def _run_single(
        self, case, backend, profiles, sink, t0, *, workspace_root: str | None = None
    ) -> TurnOutcome:
        provider = self._provider or build_provider(_eval_credentials())
        # toolset="worker" gets the REAL delegated-worker registry (builtins + the
        # worker-only ``escalate`` upward channel), so a worker-path eval exercises
        # escalate exactly as production does; "ceo" gets the coordinator read-only subset.
        tools = (
            build_ceo_tool_registry()
            if case.toolset == "ceo"
            else build_worker_registry(backend=backend)
        )
        profile = profiles.get("chat")
        citations: list[dict] = []
        ctx = ToolContext(
            execution_id=new_id(),
            run_id=new_id(),
            agent_id=_EVAL_USER_ID,
            backend=backend,
            user_id=_EVAL_USER_ID,
        )
        messages = [
            *_history_messages(case.history),
            LLMMessage(role="user", content=case.user_message),
        ]
        # B2: collect the engine's non-default terminal reason (degraded / unproductive)
        # the same way the run executor does, so the eval outcome surfaces it instead of
        # masking it as a rounds-derived end_turn.
        finish_override: list[FinishReason] = []
        content, _reasoning, usage, rounds = await react_loop(
            messages=messages,
            llm=provider,
            tools=tools,
            sink=sink,
            tool_context=ctx,
            profile=profile,
            citation_sink=citations,
            finish_override_sink=finish_override,
            # 交付正文只留最终交付 (Fork-B, 全队对称): score the SAME deliverable a real
            # single-agent turn persists — the executor_captain path is deliverable_only,
            # so an eval must be too, else it grades process narration users never see.
            deliverable_only=True,
        )
        return single_outcome(
            content,
            usage,
            rounds,
            profile=profile,
            model=profiles.model,
            sink=sink,
            citations=citations,
            latency_ms=_ms(t0),
            finish_override=finish_override[0] if finish_override else None,
            workspace_root=workspace_root,
        )

    async def _run_team(
        self, case, backend, profiles, sink, t0, *, workspace_root: str | None = None
    ) -> TurnOutcome:
        result = await run_chat_pipeline(
            conversation_id=new_id(),
            user_message=case.user_message,
            history=case.history,
            sink=sink,
            user_id=_EVAL_USER_ID,
            backend=backend,
            approvals_enabled=False,
            profile_set=profiles,
        )
        return team_outcome(result, sink, latency_ms=_ms(t0), workspace_root=workspace_root)

    def _fixture_root(self, case: EvalCase) -> Path:
        """用例的工作区现场：指定 fixture → 拷贝到临时目录再挂（源只读）；否则一次性临时目录。"""
        if case.workspace_fixture:
            root = self._fixtures_dir / case.workspace_fixture
            if not root.is_dir():
                raise EvalConfigError(f"[{case.id}] workspace_fixture 目录不存在: {root}")
            # copytree 隔离：worker 原地改文件不得污染仓内 fixtures（否则后续用例 FN）。
            dest = Path(tempfile.mkdtemp(prefix="agentcore-eval-"))
            shutil.copytree(root, dest, dirs_exist_ok=True)
            return dest
        return Path(tempfile.mkdtemp(prefix="agentcore-eval-"))
