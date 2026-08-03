"""Delegate completion criteria: verify delivery before CEO can treat delegate as done."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

from agentcore.core.logging import get_logger
from agentcore.llm.provider.protocol import LLMMessage
from agentcore.runtime.runs.types import RunPhase, RunState

if TYPE_CHECKING:
    from agentcore.runtime.runs.plan import RunPlan

logger = get_logger(__name__)

CompletionCriteriaKind = Literal[
    "files_written",
    "code_verified",
    "runtime_ready",
    "graph_consistent",
    "custom",
]
DEFAULT_COMPLETION_CRITERIA: CompletionCriteriaKind = "files_written"
_CRITERIA_KINDS = frozenset(
    {
        "files_written",
        "code_verified",
        "runtime_ready",
        "graph_consistent",
        "custom",
    }
)
# Where the resolved criteria came from — drives CEO-facing gap / echo copy.
# ``text_inferred`` is retained only for historical gap-format strings; the resolver
# no longer produces it (检索与交付约束前置提案 B1).
CriteriaSource = Literal["explicit", "structured", "text_inferred"]

# Soft overlay: TypeScript landings may remind about verify (not task-text inference).
# Soft only — never blocks the batch / criteria_unmet; explicit code_verified still binds.
_TYPESCRIPT_SUFFIXES = frozenset({".ts", ".tsx"})
# Soft overlay: .ts/.tsx/.vue landings may remind about import closure (parallel to D2).
# Soft only; explicit graph_consistent still binds.
_GRAPH_SOURCE_SUFFIXES = frozenset({".ts", ".tsx", ".vue"})

# Commands that count as code verification when run via terminal / code_execute.
_VERIFY_COMMAND_RE = re.compile(
    r"\b(?:"
    r"tsc\b|vue-tsc\b|typecheck\b|"
    r"(?:npm|pnpm|yarn)\s+run\s+(?:test|typecheck|build|lint)\b|"
    r"(?:npm|pnpm|yarn)\s+test\b|"
    r"pytest\b|cargo\s+(?:test|check|build)\b|go\s+test\b|"
    r"(?:mvn|gradlew?)\s+test\b"
    r")",
    re.IGNORECASE,
)
# Task text hints that imply run/open/install acceptance — non-binding soft warnings
# only (``execution_capability_warning``). Binding criteria MUST be explicit / structured;
# never resolve to ``code_verified`` / ``runtime_ready`` from these hints (提案 B1).
_EXECUTION_TASK_HINTS = re.compile(
    r"(运行|启动|打开|安装|跑通|联调|验收|测试通过|"
    r"npm\s+(run|start)|pnpm\s+(run|start)|yarn\s+(run|start|dev)|"
    r"python\s+-m|uv\s+run|pip\s+run|cargo\s+run|go\s+run|进程)",
    re.IGNORECASE,
)

# Long-running / process-ready task shape — pairs with ``runtime_ready`` (not code_verified).
# Require a process/service anchor after「启动」— bare「启动调研」must NOT match.
_RUNTIME_READY_TASK_HINTS = re.compile(
    r"(?:"
    r"启动(?:项目|应用|服务|服务器|开发服务器|dev)"
    r"|把(?:这个|该)?项目跑起来|把服务跑起来|跑起来(?:项目|服务|应用|开发服务器)?"
    r"|开发服务器|dev\s*server|长驻|后台进程|wait_for"
    r"|(?:npm|pnpm|yarn|bun)\s+(?:run\s+)?(?:dev|start)\b"
    r"|(?:npx|bunx)\s+(?:vite|next|nuxt|webpack-dev-server)\b"
    r"|vite\s+--host|next\s+dev|uvicorn\b|runserver\b|flask\s+run\b"
    r")",
    re.IGNORECASE,
)

# Compile / test / build verify task shape — pairs with ``code_verified``.
# Keep aligned with ``_VERIFY_COMMAND_RE`` (kind-fit must not drift from evidence).
_VERIFY_TASK_HINTS = re.compile(
    r"(?:"
    r"\btsc\b|vue-tsc\b|typecheck|type-check|pytest|vitest|\bjest\b|unittest"
    r"|(?:npm|pnpm|yarn)\s+run\s+(?:test|build|typecheck|lint)\b"
    r"|(?:npm|pnpm|yarn)\s+test\b"
    r"|cargo\s+(?:test|check|build)\b|go\s+test\b"
    r"|(?:mvn|gradlew?)\s+test\b"
    r"|跑通测试|单元测试|集成测试|编译检查|类型检查|build\s*通过|测试通过"
    r")",
    re.IGNORECASE,
)

# Task text hints that the DELIVERABLE itself needs a program run to materialise —
# binary / playable artifacts (a .pptx via python-pptx, a rendered video, an exe…).
# Heuristic-only (能力闸分级): a hit NEVER blocks, it just rides a soft warning on the
# delegate result when the turn has no execution class (宁可漏不可错杀).
_BINARY_ARTIFACT_HINTS = re.compile(
    r"(python-pptx|openpyxl|ffmpeg|可播放|可直接播放|二进制|可执行文件|"
    r"\.pptx|\.docx|\.xlsx|\.exe|\.apk|\.mp4|\.mp3|\.wav|\.avi|\.mov)",
    re.IGNORECASE,
)

# Office / document deliverable shape — pairs with ``files_written``, never ``code_verified``.
# Binding gate (案 20260803-ppt-office-code-verified-mismatch A)：文档类禁源码仓式验收。
_OFFICE_ARTIFACT_SUFFIXES = frozenset({".pptx", ".docx", ".xlsx", ".odt", ".rtf"})
_OFFICE_DELIVERABLE_HINTS = re.compile(
    r"(?:"
    r"\.pptx|\.docx|\.xlsx|\.odt|\.rtf|"
    r"python-pptx|openpyxl|"
    r"幻灯片|演示文稿|课件|"
    r"\bPPTX?\b|PowerPoint|"
    r"Word\s*文档|Excel(?:表|表格|文件)?"
    r")",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CompletionCriteria:
    kind: CompletionCriteriaKind
    description: str = ""
    # Structured「怎么算修好」for code_verified / repair batches (命令或等价说明).
    verify_command: str = ""


@dataclass(frozen=True)
class ResolvedCompletion:
    """Resolved batch-level criteria plus provenance for gap messaging / logging."""

    criteria: CompletionCriteria | None
    source: CriteriaSource | None = None


def _clean_how_fixed(*parts: Any) -> str:
    """First non-empty how-fixed string (verify_command / description / playbook slot)."""
    for part in parts:
        if part is None:
            continue
        text = str(part).strip()
        if text:
            return text
    return ""


def how_fixed_text(criteria: CompletionCriteria | None) -> str:
    """CEO/worker-facing「怎么算修好」from structured criteria fields."""
    if criteria is None:
        return ""
    return _clean_how_fixed(criteria.verify_command, criteria.description)


def parse_completion_criteria(raw: Any) -> CompletionCriteria | None:
    """Parse delegate ``completion_criteria``; ``None`` means no explicit enforcement."""
    if raw is None:
        return None
    if isinstance(raw, str):
        if raw in _CRITERIA_KINDS:
            return CompletionCriteria(kind=raw)  # type: ignore[arg-type]
        return CompletionCriteria(kind=DEFAULT_COMPLETION_CRITERIA)
    if isinstance(raw, dict):
        kind = raw.get("type") or raw.get("kind") or DEFAULT_COMPLETION_CRITERIA
        if kind not in _CRITERIA_KINDS:
            kind = DEFAULT_COMPLETION_CRITERIA
        desc = str(raw.get("description") or "")
        verify_cmd = _clean_how_fixed(
            raw.get("verify_command"),
            raw.get("verify"),
            raw.get("acceptance"),
        )
        return CompletionCriteria(
            kind=kind,  # type: ignore[arg-type]
            description=desc,
            verify_command=verify_cmd,
        )
    return CompletionCriteria(kind=DEFAULT_COMPLETION_CRITERIA)


def extract_playbook_how_fixed(playbook_args: Any) -> str:
    """``verify`` / ``verify_command`` / ``acceptance`` slot from playbook_args."""
    if not isinstance(playbook_args, dict):
        return ""
    return _clean_how_fixed(
        playbook_args.get("verify_command"),
        playbook_args.get("verify"),
        playbook_args.get("acceptance"),
    )


def default_repair_code_criteria(playbook_args: Any) -> dict[str, str]:
    """Top-level ``completion_criteria`` object for ``repair_code`` (code_verified + how-fixed)."""
    how = extract_playbook_how_fixed(playbook_args)
    out: dict[str, str] = {"type": "code_verified"}
    if how:
        out["verify_command"] = how
    return out


def validate_repair_how_fixed(
    raw: Any,
    *,
    playbook: str | None = None,
    playbook_args: Any = None,
    complexity_hint: str | None = None,
) -> str | None:
    """Reject repair-related delegates that omit structured「怎么算修好」.

    Triggers (any):
    - ``playbook=repair_code``
    - explicit ``completion_criteria`` kind ``code_verified``
    - ``complexity_hint=light`` **and** explicit ``code_verified`` (验的 light)

    How-fixed may come from ``verify_command`` / ``description`` on criteria, or
    from ``playbook_args.verify`` / ``verify_command`` / ``acceptance``.
    """
    pb = (playbook or "").strip()
    parsed = parse_completion_criteria(raw) if raw is not None else None
    kind = parsed.kind if parsed is not None else None
    hint = (complexity_hint or "").strip()
    repair_related = pb == "repair_code" or kind == "code_verified"
    if not repair_related:
        return None
    how = _clean_how_fixed(
        how_fixed_text(parsed),
        extract_playbook_how_fixed(playbook_args),
    )
    if how:
        return None
    if pb == "repair_code":
        return (
            "修码收口契约：playbook=repair_code 须写清「怎么算修好」。"
            "在 playbook_args 填 verify（或 verify_command / acceptance），"
            "例如 verify=\"pytest tests/test_foo.py -q\" 或 "
            "verify=\"python -c 'from app import foo; assert foo()'\"；"
            "也可在顶层 completion_criteria 用 "
            '{"type":"code_verified","verify_command":"…"}。'
        )
    if hint == "light":
        return (
            "修码收口契约：light 且 completion_criteria=code_verified 时须写清"
            "「怎么算修好」（verify_command 或 description），"
            "例如 {\"type\":\"code_verified\",\"verify_command\":\"pytest -q\"}。"
            "若本批只需落盘、不强制跑通验证，请改用 files_written 或省略验收。"
        )
    return (
        "修码收口契约：completion_criteria=code_verified 须写清「怎么算修好」"
        "（对象字段 verify_command 或 description），"
        "例如 {\"type\":\"code_verified\",\"verify_command\":\"pnpm test\"}；"
        "禁止只写裸字符串 code_verified 而不说明跑哪条命令。"
    )


def plan_suggests_code_verification(plan: RunPlan) -> bool:
    """True when any worker task/objective reads like run/open/install acceptance."""
    for node in plan.nodes:
        text = f"{node.task}\n{node.objective}".strip()
        if text and _EXECUTION_TASK_HINTS.search(text):
            return True
    return False


def plan_suggests_runtime_ready(plan: RunPlan) -> bool:
    """True when any task reads like start-a-long-running-process acceptance."""
    for node in plan.nodes:
        text = f"{node.task}\n{node.objective}".strip()
        if text and _RUNTIME_READY_TASK_HINTS.search(text):
            return True
    return False


def plan_suggests_verify(plan: RunPlan) -> bool:
    """True when any task reads like compile/test/build verify acceptance."""
    for node in plan.nodes:
        text = f"{node.task}\n{node.objective}".strip()
        if text and _VERIFY_TASK_HINTS.search(text):
            return True
    return False


def plan_declares_artifacts(plan: RunPlan) -> bool:
    """True when any worker deliverable declares a non-empty ``artifacts`` list."""
    for node in plan.nodes:
        d = node.deliverable
        if d is not None and d.artifacts:
            return True
    return False


def plan_declares_files_form(plan: RunPlan) -> bool:
    """True when any worker deliverable declares ``form=files``."""
    for node in plan.nodes:
        d = node.deliverable
        if d is not None and d.form == "files":
            return True
    return False


def plan_all_workers_prose(plan: RunPlan) -> bool:
    """True when every worker explicitly declares ``form=prose`` (non-empty plan)."""
    if not plan.nodes:
        return False
    for node in plan.nodes:
        d = node.deliverable
        if d is None or d.form != "prose":
            return False
    return True


def plan_has_writable_worker(plan: RunPlan) -> bool:
    """True when at least one worker can land files (not ``form=prose``).

    ``form`` omitted (legacy) keeps write tools; only explicit ``prose`` withholds them.
    """
    if not plan.nodes:
        return False
    for node in plan.nodes:
        d = node.deliverable
        if d is None or d.form != "prose":
            return True
    return False


# Acceptance kinds that need at least one writable (form=files or equivalent) worker.
_FILE_LANDING_CRITERIA_KINDS = frozenset(
    {"files_written", "code_verified", "graph_consistent"}
)


def validate_completion_against_forms(
    raw: Any,
    plan: RunPlan,
) -> str | None:
    """Reject file-landing acceptance when no writable worker exists (契约矛盾).

    ``files_written`` / ``code_verified`` / ``graph_consistent`` need at least one
    ``form=files`` (or non-prose) worker. Mixed ``repair_code`` (patch files + verify
    prose) passes. ``runtime_ready`` + all-prose is allowed (ready-check need not write).

    Returns an error message for the CEO, or ``None`` when the combination is fine.
    """
    if raw is None:
        return None
    criteria = parse_completion_criteria(raw)
    if criteria is None or criteria.kind not in _FILE_LANDING_CRITERIA_KINDS:
        return None
    if plan_has_writable_worker(plan):
        return None
    kind = criteria.kind
    return (
        f"契约矛盾：completion_criteria={kind} 要求至少一名可改文件/落盘的队员"
        f"（deliverable.form=files），但本批没有任何可写盘 worker"
        f"（均为 form=prose 或不存在队员）。"
        "改法：① 把修补/落盘员改为 form=files（验证员/诊断员可继续 prose）；"
        "② 纯文字交付请省略该类验收，或改用 runtime_ready（仅启服/就绪检查）。"
    )


def validate_cold_start_explore_deliverables(
    plan: RunPlan,
    *,
    explicit_criteria: Any = None,
) -> str | None:
    """Hard-reject thin explore teams while cold-start explore is pending.

    ``form`` / ``artifacts`` are orthogonal to explore-pending: workers may land
    notes under ``write_scope=explore_memory`` (enforced at write-tool layer).
    Explore teams must fan out ≥2 angles (1 worker 包办整仓 is rejected).
    ``explicit_criteria`` is retained for call-site compat (unused).
    Returns CEO-facing error text, or ``None`` when the batch is fine.
    """
    del explicit_criteria  # API compat; form/artifacts no longer gated here.
    if len(plan.nodes) < 2:
        return (
            "冷启动探索未完成：探路委派须 ≥2 角并行（例：目录/入口 vs 设计·约定文档），"
            "禁止 1 人包办整仓摸底。请拆成至少两名调研 worker 后重调 delegate。"
        )
    return None


def plan_mentions_binary_artifact(plan: RunPlan) -> bool:
    """True when any worker task/objective reads like a binary / playable deliverable."""
    for node in plan.nodes:
        text = f"{node.task}\n{node.objective}".strip()
        if text and _BINARY_ARTIFACT_HINTS.search(text):
            return True
    return False


def _path_looks_office(path: str) -> bool:
    lowered = path.lower().replace("\\", "/")
    return any(
        lowered.endswith(suf) or lowered.endswith(f"*{suf}") or f"*{suf}" in lowered
        for suf in _OFFICE_ARTIFACT_SUFFIXES
    )


def plan_suggests_office_deliverable(plan: RunPlan) -> bool:
    """True when any worker task/artifacts read like Office/document landing.

    Used by :func:`validate_criteria_kind_fit` to reject ``code_verified`` on
    PPT/Word/Excel batches (acceptance must be ``files_written`` / artifact landing).
    """
    for node in plan.nodes:
        text = f"{node.task}\n{node.objective}".strip()
        if text and _OFFICE_DELIVERABLE_HINTS.search(text):
            return True
        d = node.deliverable
        if d is None:
            continue
        name = str(getattr(d, "name", "") or "").strip()
        if name and _path_looks_office(name):
            return True
        for art in d.artifacts or []:
            if art and _path_looks_office(str(art)):
                return True
    return False


def _resolved_code_verified(raw: Any, plan: RunPlan) -> bool:
    """Whether this delegate WILL be held to ``code_verified`` at completion.

    Uses ``resolve_completion_with_source`` — the exact predicate ``drive.py`` enforces
    after the batch finishes (explicit / structured ``form``/``artifacts`` only; no
    task-text inference). Gate and enforcement share one resolution.
    """
    criteria = resolve_completion_criteria(raw, plan)
    return criteria is not None and criteria.kind == "code_verified"


def _resolved_runtime_ready(raw: Any, plan: RunPlan) -> bool:
    """Whether this delegate WILL be held to ``runtime_ready`` at completion."""
    criteria = resolve_completion_criteria(raw, plan)
    return criteria is not None and criteria.kind == "runtime_ready"


def _explicit_criteria_kind(raw: Any) -> CompletionCriteriaKind | None:
    """Kind from CEO-explicit raw only (ignores structured files_written inference)."""
    if raw is None:
        return None
    parsed = parse_completion_criteria(raw)
    return parsed.kind if parsed is not None else None


def validate_criteria_kind_fit(raw: Any, plan: RunPlan) -> str | None:
    """Reject explicit criteria that contradict the batch's acceptance shape.

    ``code_verified`` = compile/test/build evidence; ``runtime_ready`` = long-running
    process ready. Mixing them (e.g. ``code_verified`` on「启动 npm run dev」) is a
    contract error — not a soft gap after the worker already succeeded.

    Office/document batches (``.pptx`` / ``.docx`` / ``.xlsx`` …) must not use
    ``code_verified`` — that is source-repo verify semantics; use ``files_written``.
    """
    kind = _explicit_criteria_kind(raw)
    if kind is None:
        return None
    if kind == "code_verified" and plan_suggests_office_deliverable(plan):
        return (
            "契约矛盾：completion_criteria=code_verified 只验收编译/测试/build"
            "（tsc|typecheck|test|build 等 exit 0），不能验收 Office/文档落盘"
            "（.pptx/.docx/.xlsx 等）。本批是文档/Office 交付。"
            "改法：改用 completion_criteria=files_written"
            "（常配合 deliverable.form=files / artifacts）；"
            "禁止对文档类套源码仓式 code_verified。"
        )
    startish = plan_suggests_runtime_ready(plan)
    verifyish = plan_suggests_verify(plan)
    if kind == "code_verified" and startish and not verifyish:
        return (
            "契约矛盾：completion_criteria=code_verified 只验收编译/测试/build"
            "（tsc|typecheck|test|build 等 exit 0），不能验收「启动开发服务器 / 长驻进程」。"
            "本批任务是进程启动形。改法：改用 completion_criteria=runtime_ready"
            "（terminal start + wait_for 就绪）；若只要启动汇报、不强制引擎验收，可省略"
            "completion_criteria。"
        )
    if kind == "runtime_ready" and verifyish and not startish:
        return (
            "契约矛盾：completion_criteria=runtime_ready 只验收长驻进程就绪"
            "（terminal start + wait_for matched），不能验收编译/测试。"
            "本批任务是验证形。改法：改用 completion_criteria=code_verified。"
        )
    return None


def _criteria_fingerprint(raw: Any) -> str | None:
    """Stable compare key for hoist / conflict (kind + optional custom description)."""
    criteria = parse_completion_criteria(raw)
    if criteria is None:
        return None
    if criteria.kind == "custom":
        return f"custom:{criteria.description.strip()}"
    return criteria.kind


def hoist_task_completion_criteria(
    top_level: Any,
    tasks_raw: list[Any],
) -> tuple[Any, str | None]:
    """Lift mis-nested task-level ``completion_criteria`` when top-level is omitted.

    Formal contract remains top-level only — this is tolerance, not a schema change.
    Returns ``(resolved_raw, error)``:
    - top-level present → unchanged, ignore task-level
    - top-level missing, one task / multi-task same value → hoist that value
    - multi-task conflicting values → ``(None, ceo_facing_error)``
    - nothing nested → ``(None, None)``
    """
    if top_level is not None:
        return top_level, None

    found: list[tuple[int, Any, str]] = []
    for idx, task in enumerate(tasks_raw):
        if not isinstance(task, dict):
            continue
        if "completion_criteria" not in task:
            continue
        nested = task.get("completion_criteria")
        fp = _criteria_fingerprint(nested)
        if fp is None:
            continue
        found.append((idx, nested, fp))

    if not found:
        return None, None

    fingerprints = {fp for _, _, fp in found}
    if len(fingerprints) > 1:
        parts = [f"tasks[{i}]={fp}" for i, _, fp in found]
        return None, (
            "委派参数无效：多个 task 内嵌的 completion_criteria 互相冲突"
            f"（{'; '.join(parts)}）。"
            "请删掉 tasks[].completion_criteria，改在 delegate 顶层写一条"
            "（与 tasks 同级，如 files_written / code_verified / runtime_ready / "
            "graph_consistent / "
            "{\"type\":\"custom\",\"description\":\"…\"}）；"
            "若确需分 task 差异验收，请拆成多次 delegate。"
        )

    # Single value (one task, or multi-task unanimous) → hoist.
    _, nested, fp = found[0]
    logger.info(
        "delegate.completion_criteria_hoisted",
        criteria=fp,
        task_count=len(found),
        task_indexes=[i for i, _, _ in found],
    )
    return nested, None


def validate_execution_capability(
    raw: Any,
    plan: RunPlan,
    backend: Any,
) -> str | None:
    """Hard gate: execution-class criteria on a workspace that cannot satisfy them.

    - ``code_verified`` needs ``code_execution_enabled_for`` (code_execute / test_run).
    - ``runtime_ready`` needs a local workspace with ``terminal``.

    Returns the CEO-facing rejection message, or ``None`` when fine.
    Orthogonal to :func:`validate_code_verified_worker_tools` (worker tool surface).
    """
    if _resolved_runtime_ready(raw, plan):
        if backend is None or getattr(backend, "location", None) == "local":
            return None
        return (
            "无法按 runtime_ready 验收：本回合无本机 terminal（云端沙箱不能托管长驻"
            "开发服务器），这条委派会空跑。出路："
            "① 需要真启动服务 → 立即发 ask_user 卡（桌面在线时：本会话要跑通 → "
            "action=bind_local_folder；打开本机目录当项目 → action=open_local_project；"
            "勿用纯文本询问；bind≠打开项目）；完成后再委派；"
            "② 改为给出本地启动步骤（form=prose 或 files 落盘说明），省略 "
            "completion_criteria=runtime_ready，并在收尾标出「未在本回合启动」；"
            "③ 交付形态拿不准 → 先 ask_user 与用户对齐再委派。"
        )
    if not _resolved_code_verified(raw, plan):
        return None
    from agentcore.tools.builtin import code_execution_enabled_for

    if code_execution_enabled_for(backend):
        return None
    return (
        "无法按 code_verified 验收：本回合工作区为云端沙箱、未装配 code_execute / test_run"
        "（执行环境不可用），worker 写得了文件但运行不了代码，这条委派会空跑。出路："
        "① 需要真跑通 → 立即发 ask_user 卡（桌面在线时：本会话要跑通 → "
        "action=bind_local_folder；打开本机目录当项目 → action=open_local_project；"
        "勿用纯文本询问；bind≠打开项目）；完成后再委派；"
        "② 改为当前环境可交付的形态 → 落盘生成脚本 / 源文件 + 使用说明"
        "（deliverable.form=files，completion_criteria=files_written，任务文案不写"
        "「运行 / 跑通」类要求），并在收尾向用户显式标出「未运行验证」的交付缺口；"
        "③ 交付形态拿不准 → 先 ask_user 与用户对齐再委派。"
    )


def validate_code_verified_worker_tools(raw: Any, plan: RunPlan) -> str | None:
    """真纯丙：退役「白名单无执行类工具」入闸硬拒（与 :func:`validate_files_worker_tools` 同向）。

    环境是否装配执行类工具仍由 :func:`validate_execution_capability` 等回答。
    """
    del raw, plan
    return None


def node_holds_write_tools(spec: Any) -> bool:
    """真纯丙：不再用 ``spec.tools`` 白名单判断写盘能力；默认视为具备。

    H2 已取消 ``form=prose`` 硬卸写盘；本函数恒 True（写盘仍过用户授权 / write_scope）。
    """
    del spec
    return True


def validate_files_worker_tools(raw: Any, plan: RunPlan) -> str | None:
    """真纯丙·M1：退役「白名单无写 → no_write_tools」入闸硬拒。

    落盘仍靠 deliverable / completion_criteria 与用户写盘授权；不再因窄 tools
    名单拒派。保留函数与调用点以免契约漂移，恒返回 ``None``。
    """
    del raw, plan
    return None


def execution_capability_warning(
    raw: Any,
    plan: RunPlan,
    backend: Any,
) -> str | None:
    """Soft warning: binary-artifact / run-flavoured smell with no execution class.

    Fires only when the hard gate did NOT (resolved criteria is not ``code_verified``
    or ``runtime_ready``). Never blocks.
    """
    if _resolved_code_verified(raw, plan) or _resolved_runtime_ready(raw, plan):
        return None  # hard gate owns this case
    if not (plan_suggests_code_verification(plan) or plan_mentions_binary_artifact(plan)):
        return None
    from agentcore.tools.builtin import code_execution_enabled_for

    if code_execution_enabled_for(backend):
        if (
            plan_suggests_runtime_ready(plan)
            and getattr(backend, "location", None) != "local"
        ):
            return (
                "[能力提示] 本批任务像「启动长驻进程 / 开发服务器」，但当前无本机 "
                "terminal：worker 无法真正托管服务。请在绑定本机执行环境或打开本地项目后使用 "
                "completion_criteria=runtime_ready，或改为启动步骤说明并省略进程就绪验收。"
            )
        return None
    return (
        "[能力提示] 本回合执行环境未装配（云端沙箱，无 code_execute / test_run / terminal）："
        "任务文案涉及「运行 / 启动 / 生成二进制或可播放产物」，worker 只能写脚本 / 文件，"
        "无法真正运行或生成此类产物。收尾时请把交付缺口如实标给用户"
        "（如「脚本已落盘、未运行验证」），或立即发 ask_user 卡"
        "（桌面在线时：本会话要跑通 → action=bind_local_folder；"
        "打开本机目录当项目 → action=open_local_project；"
        "勿用纯文本询问；bind≠打开项目）后重派。"
    )


def resolve_completion_with_source(
    raw: Any,
    plan: RunPlan | None = None,
    *,
    suppress_structured_files_written: bool = False,
) -> ResolvedCompletion:
    """Resolve criteria with provenance.

    Priority (explicit beats structured; omit = unenforced):
    1. CEO explicit ``completion_criteria`` (top-level / hoisted) — always binds,
       including during cold-start explore.
    2. Structured deliverable signals: ``artifacts`` or ``form=files`` → ``files_written``
       (skipped when ``suppress_structured_files_written``, e.g. cold-start explore
       pending — only explicit criteria bind then).
    3. Otherwise → unenforced (including all-prose and run-flavoured task text)

    Task-text run/open/install hints never bind criteria (提案 B1); they only feed
    non-binding soft warnings via :func:`execution_capability_warning`.
    """
    if raw is not None:
        return ResolvedCompletion(parse_completion_criteria(raw), "explicit")
    if plan is None:
        return ResolvedCompletion(None, None)
    if suppress_structured_files_written:
        return ResolvedCompletion(None, None)
    if plan_declares_artifacts(plan) or plan_declares_files_form(plan):
        return ResolvedCompletion(CompletionCriteria(kind="files_written"), "structured")
    return ResolvedCompletion(None, None)


def resolve_completion_criteria(
    raw: Any,
    plan: RunPlan | None = None,
    *,
    suppress_structured_files_written: bool = False,
) -> CompletionCriteria | None:
    """Parse explicit criteria, or infer from structured deliverable signals.

    See :func:`resolve_completion_with_source` for priority. Never binds criteria
    from task text; never auto-infers ``files_written`` for an all-prose batch.
    """
    return resolve_completion_with_source(
        raw,
        plan,
        suppress_structured_files_written=suppress_structured_files_written,
    ).criteria


def format_resolved_acceptance_echo(resolved: ResolvedCompletion) -> str:
    """CEO-facing one-liner echoing the batch acceptance this delegate will enforce.

    Always produced (including「未启用」) so the CEO can see / correct criteria in-turn
    (提案 B1 补偿②).
    """
    if resolved.criteria is None:
        return "本批验收：未启用"
    kind = resolved.criteria.kind
    how = how_fixed_text(resolved.criteria)
    how_suffix = f"；怎么算修好：{how}" if how else ""
    if resolved.source == "explicit":
        return f"本批验收：{kind}（显式声明）{how_suffix}"
    if resolved.source == "structured":
        return f"本批验收：{kind}（结构化交付声明）{how_suffix}"
    return f"本批验收：{kind}{how_suffix}"


def node_holds_execution_tools(spec: Any) -> bool:
    """真纯丙：不再用 ``spec.tools`` 白名单判断执行类工具；默认视为具备。

    环境是否真装配 ``code_execute`` / ``test_run`` / ``terminal`` 仍由 registry /
    ``validate_execution_capability`` 等能力闸回答，与名单无关。
    """
    del spec
    return True


def should_inject_batch_acceptance(spec: Any, criteria: CompletionCriteria | None) -> bool:
    """Whether this worker should see batch ``completion_criteria`` in 交付物规格.

    真纯丙下执行类工具不再按 ``spec.tools`` 白名单判定（恒视为具备）。
    - ``runtime_ready`` / ``code_verified``: 凡有批次验收即注入。
    - ``files_written`` (提案 B2): 仍要求 ``form=files`` — research/prose
      peers 不因冗余落盘提示被打扰。
    """
    if criteria is None:
        return False
    if not node_holds_execution_tools(spec):
        return False
    if criteria.kind in ("runtime_ready", "code_verified"):
        return True
    deliverable = getattr(spec, "deliverable", None)
    return not (deliverable is None or getattr(deliverable, "form", None) != "files")


def format_batch_acceptance_for_worker(criteria: CompletionCriteria) -> str:
    """One deliverable-spec line telling the worker the batch acceptance bar."""
    if criteria.kind == "files_written":
        return (
            "- 本批验收：files_written（至少一名持执行类工具的落盘 worker 须将产物"
            "写入工作区；你若负责落盘，请用 file_write / str_replace 完成）"
        )
    if criteria.kind == "code_verified":
        how = how_fixed_text(criteria)
        if how:
            how_line = (
                f"；约定命令：用 test_run（check=command，command=`{how}`）跑通且 exit 0"
            )
        else:
            how_line = (
                "；用 test_run 跑通项目检查（check=install|test|typecheck|build，或 "
                "check=command + 约定命令）且 exit 0"
            )
        return (
            "- 本批验收：code_verified（须至少一次成功落盘 + 外环验绿：默认走有界项目验证 "
            "test_run：tsc|typecheck|test|build 等；【不要】把慢 build/全量 tsc 塞进 "
            "code_execute；内环 code_diagnostics / 写盘诊断不能代替外环验绿；"
            "全量 typecheck/build/`tsc -b` 仅验收员执行，修码 worker "
            "用内环诊断自检，禁止三路并行全仓 tsc / 禁止修码批持 test_run；"
            "terminal 仅长驻。普通脚本/打印/启动开发服务器不算；"
            "纯 prose / 零写预存绿测不算过门；落盘用 file_write / str_replace"
            f"{how_line}；你持有执行工具时请在收尾前完成落盘与验证）"
        )
    if criteria.kind == "runtime_ready":
        return (
            "- 本批验收：runtime_ready（至少一名 worker 须用 terminal subcommand=start "
            "启动长驻进程，并设 wait_for 等到就绪信号 matched；禁止用 code_execute "
            "启服务；就绪后汇报访问地址）"
        )
    if criteria.kind == "graph_consistent":
        return (
            "- 本批验收：graph_consistent（落盘的 .ts/.tsx/.vue 相对路径与 `@/` import "
            "须指向已存在文件；禁止悬空引用）"
        )
    desc = (criteria.description or "").strip()
    if desc:
        return f"- 本批验收：custom（{desc}）"
    return "- 本批验收：custom（批次声明了自定义验收，请按任务说明对齐）"


def _code_execute_succeeded_in_transcript(transcript: list[LLMMessage]) -> bool:
    """True when at least one ``code_execute`` call completed without a non-zero exit."""
    call_names: dict[str, str] = {}
    for msg in transcript:
        if msg.role != "assistant" or not msg.tool_calls:
            continue
        for tc in msg.tool_calls:
            call_names[tc.id] = tc.function.name
    for msg in transcript:
        if msg.role != "tool" or not msg.tool_call_id:
            continue
        if call_names.get(msg.tool_call_id) != "code_execute":
            continue
        content = msg.content or ""
        if "退出码" not in content:
            return True
    return False


def _test_run_succeeded_in_transcript(transcript: list[LLMMessage]) -> bool:
    """True when at least one ``test_run`` completed with a passing verify signal.

    Accepts structured test summaries (``通过：``) and the bounded-verify header
    ``## 验证结果：通过`` (typecheck / build / command checks).
    """
    call_names: dict[str, str] = {}
    for msg in transcript:
        if msg.role != "assistant" or not msg.tool_calls:
            continue
        for tc in msg.tool_calls:
            call_names[tc.id] = tc.function.name
    for msg in transcript:
        if msg.role != "tool" or not msg.tool_call_id:
            continue
        if call_names.get(msg.tool_call_id) != "test_run":
            continue
        content = msg.content or ""
        if "测试未通过" in content or "验证未通过" in content:
            continue
        if "预算耗尽" in content or "验证未完成" in content:
            continue
        if "## 验证结果：通过" in content:
            return True
        fail_m = re.search(r"失败：(\d+)", content)
        err_m = re.search(r"错误：(\d+)", content)
        if fail_m and int(fail_m.group(1)) > 0:
            continue
        if err_m and int(err_m.group(1)) > 0:
            continue
        if "通过：" in content:
            return True
    return False


def _tool_call_args_map(transcript: list[LLMMessage]) -> dict[str, tuple[str, str]]:
    """Map ``tool_call_id → (tool_name, arguments_json)`` from assistant turns."""
    out: dict[str, tuple[str, str]] = {}
    for msg in transcript:
        if msg.role != "assistant" or not msg.tool_calls:
            continue
        for tc in msg.tool_calls:
            out[tc.id] = (tc.function.name, tc.function.arguments or "")
    return out


def _terminal_verify_succeeded_in_transcript(transcript: list[LLMMessage]) -> bool:
    """True when a ``terminal`` call ran a verify-shaped command and exited cleanly."""
    calls = _tool_call_args_map(transcript)
    for msg in transcript:
        if msg.role != "tool" or not msg.tool_call_id:
            continue
        name, args_json = calls.get(msg.tool_call_id, ("", ""))
        if name != "terminal":
            continue
        if not _VERIFY_COMMAND_RE.search(args_json):
            continue
        content = msg.content or ""
        # Prefer exited 0; also accept matched ready from a one-shot wait_for.
        if "status: exited" in content and "exit_code: 0" in content:
            return True
        if re.search(r"exit_code:\s*0\b", content) and "status: exited" in content:
            return True
        # wait_for hit on a verify command (unusual but honest).
        if ("matched: True" in content or "matched: true" in content) and (
            "status: running" in content or "status: exited" in content
        ):
            return True
    return False


def _code_execute_verify_succeeded_in_transcript(transcript: list[LLMMessage]) -> bool:
    """``code_execute`` whose code looks like typecheck/test/build and exited 0.

    Requires an explicit ``退出码：0`` (or ``退出码:0``) in the tool result — bare
    success text or missing exit marker does not count.
    """
    calls = _tool_call_args_map(transcript)
    for msg in transcript:
        if msg.role != "tool" or not msg.tool_call_id:
            continue
        name, args_json = calls.get(msg.tool_call_id, ("", ""))
        if name != "code_execute":
            continue
        if not _VERIFY_COMMAND_RE.search(args_json):
            continue
        content = msg.content or ""
        if re.search(r"退出码[：:]\s*0\b", content):
            return True
    return False


def _run_verified_in_transcript(transcript: list[LLMMessage]) -> bool:
    """Honest verify only: test_run / verify-shaped code_execute / terminal.

    Non-verify ``code_execute`` success is intentionally excluded (delivery_status
    still uses ``_code_execute_succeeded_in_transcript`` for writeback sniffing).
    """
    if not transcript:
        return False
    if _test_run_succeeded_in_transcript(transcript):
        return True
    if _code_execute_verify_succeeded_in_transcript(transcript):
        return True
    return _terminal_verify_succeeded_in_transcript(transcript)


def _is_typescript_path(path: str) -> bool:
    from pathlib import PurePosixPath

    suffix = PurePosixPath(path.replace("\\", "/")).suffix.lower()
    return suffix in _TYPESCRIPT_SUFFIXES


def _is_graph_source_path(path: str) -> bool:
    from pathlib import PurePosixPath

    suffix = PurePosixPath(path.replace("\\", "/")).suffix.lower()
    return suffix in _GRAPH_SOURCE_SUFFIXES


def _batch_landed_typescript(completed: list[RunState]) -> bool:
    """True when any COMPLETED worker landed a ``.ts`` / ``.tsx`` path."""
    for state in completed:
        for path in state.files_touched or []:
            if path and _is_typescript_path(path):
                return True
        if state.transcript:
            for path in _files_from_transcript(state.transcript):
                if path and _is_typescript_path(path):
                    return True
    return False


def _batch_landed_graph_sources(completed: list[RunState]) -> bool:
    """True when any COMPLETED worker landed a ``.ts`` / ``.tsx`` / ``.vue`` path."""
    for state in completed:
        for path in state.files_touched or []:
            if path and _is_graph_source_path(path):
                return True
        if state.transcript:
            for path in _files_from_transcript(state.transcript):
                if path and _is_graph_source_path(path):
                    return True
    return False


def _collect_graph_source_paths(completed: list[RunState]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for state in completed:
        paths = list(state.files_touched or [])
        if state.transcript:
            paths.extend(_files_from_transcript(state.transcript))
        for path in paths:
            if path and _is_graph_source_path(path) and path not in seen:
                seen.add(path)
                out.append(path)
    return out


def _graph_gap_message() -> str:
    return (
        "import 图不闭合：已落盘 .ts/.tsx/.vue 存在悬空相对路径或 `@/` 引用"
        "（缺文件；须同批补齐或修正 import）"
    )


def _append_graph_gaps(
    gaps: list[str],
    *,
    completed: list[RunState],
    backend: Any = None,
    file_map: dict[str, str] | None = None,
) -> None:
    """Append graph_consistent gaps when source texts are available."""
    from agentcore.runtime.delegate.graph_integrity import (
        format_graph_gap,
        load_source_file_map_sync,
        resolve_missing_imports,
    )

    paths = _collect_graph_source_paths(completed)
    if not paths:
        return
    texts: dict[str, str] = dict(file_map or {})
    if not texts and backend is not None:
        texts = load_source_file_map_sync(backend, paths)
    if not texts:
        # No readable sources — cannot honestly claim a miss; skip (drive_finalize
        # should pass an async-loaded file_map for cloud/local channel backends).
        return
    missing = resolve_missing_imports(texts)
    if not missing:
        return
    msg = format_graph_gap(missing) or _graph_gap_message()
    if msg not in gaps:
        gaps.append(msg)


def _terminal_runtime_ready_in_transcript(transcript: list[LLMMessage]) -> bool:
    """True when ``terminal`` *start* reported process ready (wait_for hit).

    Requires ``subcommand=start`` in the call args. Status / matched are read from
    the metadata header (before ``output:``) so stdout cannot fake readiness.
    """
    calls = _tool_call_args_map(transcript)
    for msg in transcript:
        if msg.role != "tool" or not msg.tool_call_id:
            continue
        name, args_json = calls.get(msg.tool_call_id, ("", ""))
        if name != "terminal":
            continue
        if not re.search(r'"subcommand"\s*:\s*"start"', args_json or ""):
            continue
        content = msg.content or ""
        if "【就绪判定】wait_for 已命中" in content:
            return True
        meta = content.split("\noutput:", 1)[0]
        running = bool(re.search(r"(?m)^status:\s*running\s*$", meta))
        matched = bool(re.search(r"(?m)^matched:\s*True\s*$", meta, re.IGNORECASE))
        if running and matched:
            return True
    return False


def _run_runtime_ready_in_transcript(transcript: list[LLMMessage]) -> bool:
    """Honest process-ready only: terminal start with wait_for matched."""
    if not transcript:
        return False
    return _terminal_runtime_ready_in_transcript(transcript)


def _verify_gap_message() -> str:
    """Binding gap copy for explicit ``code_verified``."""
    return (
        "尚无 worker 成功验证代码（须 code_execute / test_run / terminal 跑通 "
        "tsc|typecheck|test|build 等；启动开发服务器不算）"
    )


def _overlay_verify_soft_note() -> str:
    """Soft reminder when .ts/.tsx landed without a verify signal (D2 overlay)."""
    return (
        "提醒（不阻断验收）：已落盘 .ts/.tsx，建议补一次验证"
        "（code_execute / test_run / terminal 跑通 tsc|typecheck|test|build；"
        "启动开发服务器不算）"
    )


def _as_overlay_soft_note(msg: str) -> str:
    """Mark auto-scan / overlay copy as soft for delivery_status (warning / notes)."""
    if "不阻断验收" in (msg or ""):
        return msg
    return f"提醒（不阻断验收）：{msg}"


def _runtime_ready_gap_message() -> str:
    return (
        "尚无 worker 报告进程就绪（须 terminal start + wait_for 命中；"
        "status=running 且 matched；禁止用 code_execute 启长驻进程）"
    )


def _worker_files_written(state: RunState) -> bool:
    if state.files_touched:
        return True
    return bool(state.transcript and _files_from_transcript(state.transcript))


def _files_from_transcript(transcript: list[LLMMessage]) -> list[str]:
    from agentcore.runtime.runs.serialize import files_touched_from_transcript

    return files_touched_from_transcript(transcript)


def check_delegate_completion(
    criteria: CompletionCriteria | None,
    results: dict[str, RunState],
    *,
    backend: Any = None,
    file_map: dict[str, str] | None = None,
) -> tuple[bool, list[str], list[str]]:
    """Return ``(ok, binding_gaps, soft_notes)`` after all workers finish.

    Explicit / structured ``criteria`` is evaluated against every COMPLETED
    worker's real signals (``files_touched``, transcript tool results, handoff
    ``debrief``, prose ``content``)—not only workers with non-empty body text.
    A pure file_write / handoff finish with empty streamed content must still be
    checked; with no matching evidence the result is a binding gap, never a
    vacuous pass — except ``files_written`` (甲⁺): unmet landing is soft_notes
    only and does **not** block the batch.

    ``ok`` is True iff ``binding_gaps`` is empty. Soft overlays (D2: .ts/.tsx
    without verify; auto import-graph scan on .ts/.tsx/.vue; 甲⁺ files_written
    unmet) produce ``soft_notes`` only — they do **not** block the batch, do
    **not** fire ``criteria_unmet``, and do **not** feed gap fingerprint / streak.
    Explicit ``code_verified`` / ``graph_consistent`` remain binding. Soft
    overlays are skipped for ``runtime_ready`` batches and when the matching
    kind is already the binding criteria.

    ``backend`` / ``file_map`` feed ``graph_consistent`` / auto-scan reads
    (``file_map`` preferred when pre-loaded async by drive_finalize).
    """
    # Include all COMPLETED workers — empty body is a valid finish mode
    # (落盘 / handoff-only). Filtering on content.strip() used to drop them
    # and vacuous-pass when the filtered set was empty.
    completed = [s for s in results.values() if s.phase is RunPhase.COMPLETED]
    if not completed:
        return True, [], []

    binding_gaps: list[str] = []
    soft_notes: list[str] = []
    if criteria is not None:
        if criteria.kind == "files_written":
            # 甲⁺：files_written（含 form=files 结构化推断）不再挡整批收工；仅 soft 提示。
            if not any(_worker_files_written(s) for s in completed):
                soft_notes.append(_as_overlay_soft_note("本批未见落盘"))
        elif criteria.kind == "code_verified":
            if not any(_run_verified_in_transcript(s.transcript) for s in completed):
                binding_gaps.append(_verify_gap_message())
            # 乙第二刀：真绿 verify 之外还须至少一次成功落盘——零写 + 预存绿测不得当修好。
            if not any(_worker_files_written(s) for s in completed):
                from agentcore.runtime.runs.serialize import format_file_landing_tools_slash

                tools = format_file_landing_tools_slash()
                binding_gaps.append(f"尚无 worker 将产物写入工作区（需要 {tools} 落盘）")
        elif criteria.kind == "runtime_ready":
            if not any(
                _run_runtime_ready_in_transcript(s.transcript or []) for s in completed
            ):
                binding_gaps.append(_runtime_ready_gap_message())
        elif criteria.kind == "graph_consistent":
            _append_graph_gaps(
                binding_gaps, completed=completed, backend=backend, file_map=file_map
            )
        elif criteria.kind == "custom":
            # custom is intentionally not engine-verified. Never block completion on it —
            # a gap here used to mark successful delegates as unfinished. Prefer
            # files_written / code_verified / runtime_ready / deliverable.artifacts.
            pass

    kind = criteria.kind if criteria is not None else None
    # Soft D2: .ts/.tsx landed without verify — remind only (not criteria_unmet).
    # Skip when binding is already code_verified, or batch is runtime_ready.
    if (
        kind not in ("runtime_ready", "code_verified")
        and _batch_landed_typescript(completed)
        and not any(
            _run_verified_in_transcript(s.transcript or []) for s in completed
        )
    ):
        soft_notes.append(_overlay_verify_soft_note())

    # Soft auto graph scan: .ts/.tsx/.vue landings → import closure reminder.
    # Explicit graph_consistent already ran as binding; skip duplicate.
    if kind not in ("runtime_ready", "graph_consistent") and _batch_landed_graph_sources(
        completed
    ):
        overlay_graph: list[str] = []
        _append_graph_gaps(
            overlay_graph, completed=completed, backend=backend, file_map=file_map
        )
        for msg in overlay_graph:
            note = _as_overlay_soft_note(msg)
            if note not in soft_notes:
                soft_notes.append(note)

    return (not binding_gaps, binding_gaps, soft_notes)


def collect_delivered_files(results: dict[str, RunState]) -> list[str]:
    """Ordered, deduped workspace paths COMPLETED workers wrote."""
    seen: set[str] = set()
    out: list[str] = []
    for state in results.values():
        if state is None or state.phase is not RunPhase.COMPLETED:
            continue
        for path in state.files_touched or []:
            if path and path not in seen:
                seen.add(path)
                out.append(path)
    return out


def gap_fingerprint(
    criteria_kind: str | None, gaps: list[str]
) -> tuple[str, ...]:
    """Stable key for same-gap streak tracking across consecutive delegates.

    Callers must pass **binding** gaps only. Soft overlays (D2 / auto graph)
    never enter fingerprint / streak. ``criteria_kind`` is the binding kind;
    unbound (``None``) uses an empty-string sentinel — not a fake enum like
    ``typescript_verify``.
    """
    kind_key = criteria_kind if criteria_kind is not None else ""
    return (kind_key, *gaps)


def format_completion_gap_message(
    gaps: list[str],
    *,
    criteria_kind: str | None = None,
    source: CriteriaSource | None = None,
    escalate: bool = False,
    delivered_files: list[str] | None = None,
) -> str:
    """CEO-facing soft-fail copy when completion criteria are unmet.

    Always names the criteria source (explicit vs inferred). Text-inferred gaps
    tell the CEO to put ``completion_criteria`` on the delegate top level.
    After the same gap appears twice in a row, escalate: list delivered artifacts
    and require fixing the acceptance declaration or accepting the delivery —
    no more retry nudge.
    """
    head = "[系统提示] 完成条件未满足（批次验收未过，不得视为成功完成）：" + "；".join(gaps)
    parts = [head]

    kind_label = criteria_kind or "（未指定）"
    if source == "explicit":
        parts.append(f"验收标准来源：CEO 显式声明（completion_criteria={kind_label}）。")
    elif source == "structured":
        parts.append(
            f"验收标准来源：结构化交付声明（deliverable.form=files / artifacts → "
            f"{kind_label}）。"
        )
    elif source == "text_inferred":
        parts.append(
            f"验收标准来源：任务文案推断（→ {kind_label}）。"
            "若实际只需落盘交付，请在 delegate 顶层显式声明 "
            "completion_criteria=files_written（与 tasks 同级，勿写进单个 task 内层），"
            "或设置 deliverable.form=files。"
        )
    else:
        if criteria_kind is not None:
            parts.append(f"验收标准：{kind_label}。")

    if escalate:
        files = delivered_files or []
        if files:
            listed = "、".join(f"`{p}`" for p in files[:24])
            parts.append(f"已交付产物：{listed}。")
        else:
            parts.append("已交付产物：（工作区尚无落盘文件）。")
        parts.append(
            "同一验收缺口已连续出现 2 次：请修正验收声明"
            "（delegate 顶层 completion_criteria / deliverable.form），"
            "或接受当前交付并收口向用户说明——不要再以相同标准重派。"
        )
    elif criteria_kind == "runtime_ready":
        # Soft-gap remediation: batch already finished — do not re-spawn the same
        # server or append_to a dead graph; reuse / browser-only first.
        parts.append(
            "补救：本批调度已结束（非仍在跑）。先用 terminal list/read 复用已有进程，"
            "或只补 browser_navigate；禁止再起同一套开发服务器；"
            "禁止对已结束图 append_to=latest；"
            "勿整锅重派，除非确认确无可用进程。"
        )

    return "\n".join(parts)


def _tool_result_failed(content: str) -> bool:
    """True when tool_exec stamped the machine failure trailer on this tool message."""
    return "<!--agentcore:tool_failed-->" in (content or "")


def _browser_navigate_failed_in_transcript(transcript: list[LLMMessage]) -> bool:
    """True when any ``browser_navigate`` result carries the tool-failed trailer."""
    if not transcript:
        return False
    calls = _tool_call_args_map(transcript)
    for msg in transcript:
        if msg.role != "tool" or not msg.tool_call_id:
            continue
        name, _ = calls.get(msg.tool_call_id, ("", ""))
        if name != "browser_navigate":
            continue
        if _tool_result_failed(msg.content or ""):
            return True
    return False


def _test_run_failed_in_transcript(transcript: list[LLMMessage]) -> bool:
    """True when a ``test_run`` was attempted and none succeeded (未过)."""
    if not transcript:
        return False
    calls = _tool_call_args_map(transcript)
    saw_test_run = False
    for msg in transcript:
        if msg.role != "tool" or not msg.tool_call_id:
            continue
        name, _ = calls.get(msg.tool_call_id, ("", ""))
        if name != "test_run":
            continue
        saw_test_run = True
    if not saw_test_run:
        return False
    return not _test_run_succeeded_in_transcript(transcript)


def _verify_shaped_command_failed_in_transcript(transcript: list[LLMMessage]) -> bool:
    """True when verify-shaped ``code_execute`` / ``terminal`` ran and none exited 0.

    Mirrors the success predicates used by ``_run_verified_in_transcript``: only
    typecheck/test/build-shaped commands count. A failed verify attempt with no
    later success must depress delivery (可用性诚实性 · 丙).
    """
    if not transcript:
        return False
    calls = _tool_call_args_map(transcript)
    saw_verify_shaped = False
    for msg in transcript:
        if msg.role != "tool" or not msg.tool_call_id:
            continue
        name, args_json = calls.get(msg.tool_call_id, ("", ""))
        if name not in ("code_execute", "terminal"):
            continue
        if not _VERIFY_COMMAND_RE.search(args_json or ""):
            continue
        saw_verify_shaped = True
    if not saw_verify_shaped:
        return False
    if _code_execute_verify_succeeded_in_transcript(transcript):
        return False
    return not _terminal_verify_succeeded_in_transcript(transcript)


def _verify_failure_descriptions(transcript: list[LLMMessage]) -> list[str]:
    """Human one-liners for verify-shaped tool failures present in ``transcript``."""
    out: list[str] = []
    if _browser_navigate_failed_in_transcript(transcript):
        out.append("浏览器验证失败（browser_navigate 未成功打开目标页）")
    if _test_run_failed_in_transcript(transcript):
        out.append("测试未通过（test_run 未全部通过）")
    if _verify_shaped_command_failed_in_transcript(transcript):
        out.append(
            "验证命令未通过（verify 形 code_execute / terminal 非零退出或执行失败）"
        )
    return out


# Machine gap reason for verify-tool failures (可用性诚实性 · 丙).
# Mirrored as ``REASON_VERIFY_FAILED`` in delivery_status (avoid circular import).
_VERIFY_FAILED_REASON = "verify_failed"


def collect_verify_failure_gaps(
    plan: RunPlan,
    results: dict[str, RunState],
) -> list[tuple[str, list[dict[str, str]]]]:
    """Per-COMPLETED-worker verify-tool failure gaps (可用性诚实性 · 丙).

    Scans worker transcripts for ``browser_navigate`` / ``test_run`` / verify-shaped
    ``code_execute``·``terminal`` failures. Each hit becomes a blocking gap row with
    ``reason=verify_failed`` so ``build_delivery_status`` cannot stay ``delivered``.
    """
    out: list[tuple[str, list[dict[str, str]]]] = []
    for node in plan.nodes:
        state = results.get(node.run_id)
        if state is None or state.phase is not RunPhase.COMPLETED:
            continue
        descriptions = _verify_failure_descriptions(state.transcript or [])
        if not descriptions:
            continue
        label = node.role or node.run_id
        rows = [
            {"description": text, "reason": _VERIFY_FAILED_REASON} for text in descriptions
        ]
        out.append((label, rows))
    return out


def collect_worker_gaps(
    plan: RunPlan,
    results: dict[str, RunState],
) -> list[tuple[str, list[dict[str, str]]]]:
    """Per-worker structured gaps for CEO synthesis (warnings + degraded handoff).

    Returns ``[(role_label, gap_rows), ...]`` only for workers that still carry
    contract / handoff / cutoff shortfalls after soft-accept — so forced
    convergence finalize (write tools withheld) still surfaces what was never
    delivered. Each gap row is ``{description, reason?}`` where ``reason`` is a
    machine code when the signal is a known cutoff
    (``token_budget`` / ``worker_timeout`` / ``degraded_handoff``).

    刀1：worker 已有落盘时 ``degraded_handoff`` 带 ``severity=warning``（备注，非硬缺口）。
    """
    from agentcore.runtime.runs.cutoff import (
        DEGRADED_HANDOFF_WARNING,
        REASON_DEGRADED_HANDOFF,
        reason_for_warning,
    )

    out: list[tuple[str, list[dict[str, str]]]] = []
    for node in plan.nodes:
        state = results.get(node.run_id)
        if state is None or state.phase is not RunPhase.COMPLETED:
            continue
        files_landed = bool(state.files_touched) or any(
            isinstance(a, dict) and a.get("status") == "accepted"
            for a in (state.file_acceptance or [])
        )
        gaps: list[dict[str, str]] = []
        seen_desc: set[str] = set()
        # Prefer first-class delivery_gaps when present (single source).
        for row in getattr(state, "delivery_gaps", None) or []:
            if not isinstance(row, dict):
                continue
            text = str(row.get("description") or "").strip()
            if not text or text in seen_desc:
                continue
            seen_desc.add(text)
            item: dict[str, str] = {"description": text}
            reason = str(row.get("reason") or "").strip()
            if reason:
                item["reason"] = reason
            severity = str(row.get("severity") or "").strip()
            if severity:
                item["severity"] = severity
            elif reason == REASON_DEGRADED_HANDOFF and files_landed:
                item["severity"] = "warning"
            gaps.append(item)
        if state.warnings:
            for raw in state.warnings:
                text = str(raw).strip()
                if not text or text in seen_desc:
                    continue
                seen_desc.add(text)
                entry: dict[str, str] = {"description": text}
                code = reason_for_warning(text)
                if code:
                    entry["reason"] = code
                    if code == REASON_DEGRADED_HANDOFF and files_landed:
                        entry["severity"] = "warning"
                gaps.append(entry)
        debrief = state.debrief if isinstance(state.debrief, dict) else None
        if debrief and debrief.get("degraded"):
            text = DEGRADED_HANDOFF_WARNING
            if text not in seen_desc:
                seen_desc.add(text)
                row = {"description": text, "reason": REASON_DEGRADED_HANDOFF}
                if files_landed:
                    row["severity"] = "warning"
                gaps.append(row)
        if gaps:
            label = node.role or node.run_id
            out.append((label, gaps))
    return out


def format_worker_gaps_block(
    gaps_by_worker: list[tuple[str, list[dict[str, str]]]] | list[tuple[str, list[str]]],
    *,
    audit_off_with_token_budget: bool = False,
) -> str:
    """CEO-facing「契约缺口」section, or "" when nobody has residual gaps.

    Cutoff reasons (token_budget / worker_timeout / degraded_handoff) are listed
    for the CEO's replan / continue decisions. User-facing gap disclosure is owned
    by structured ``delivery_status.gaps`` + the presentation layer — the synopsis
    only gets a light anti-contradiction discipline (no completeness claims).

    When any gaps exist, the closing instruction forces「部分交付」wording and bans
    「完整 / 无需审计」assertions. ``audit_off_with_token_budget`` injects a
    sampling-check tip when policy.audit is off and a token_budget gap is present.
    """
    if not gaps_by_worker:
        return ""
    has_cutoff = False
    lines = [
        "\n### ⚠️ 契约缺口（请据缺口同图点名补，勿整团重开）\n"
        "以下是各队员收尾后仍未对齐的声明交付物 / 交接缺口（含收敛强制收尾后无法再写文件"
        "留下的缺口，以及预算/超时掐断信号）。优先同一协作图 `replan(add)` +"
        "`replaces_run_id` / `continue_from_run_id` 按缺口点名补；禁止无缺口另开大派，"
        "别假装收工。\n"
    ]
    for label, gaps in gaps_by_worker:
        parts: list[str] = []
        for gap in gaps:
            if isinstance(gap, dict):
                desc = str(gap.get("description") or "").strip()
                reason = str(gap.get("reason") or "").strip()
            else:
                desc = str(gap).strip()
                reason = ""
            if not desc:
                continue
            if reason:
                has_cutoff = True
                parts.append(f"{desc}〔原因码 {reason}〕")
            else:
                parts.append(desc)
        if parts:
            lines.append(f"- **{label}**：{'；'.join(parts)}")
    lines.append(
        "\n**【终稿诚实性·部分交付】**上方契约缺口非空：终稿必须使用「部分交付 / 尚未齐备」"
        "类措辞，点明未闭合缺口与建议下一步；"
        "【禁止】写「完整交付 / 全部完成 / 可运行无缺 / 无需审计 / 团队已交付完毕」等完成度断言。"
    )
    if has_cutoff:
        lines.append(
            "结构化交付缺口已由系统对账卡呈现，概览正文不必逐条复述掐断原因；"
            "可建议续派、绑定本机执行环境或 continue_from_run_id。"
        )
    if audit_off_with_token_budget:
        lines.append(
            "**【建议抽检】**本批未开 audit，且存在 token_budget 掐断缺口："
            "请在终稿提示用户抽检关键落盘文件 / 续派补齐，勿宣称已充分审计。"
        )
    return "\n".join(lines) + "\n"
