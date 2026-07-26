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

CompletionCriteriaKind = Literal["files_written", "code_verified", "custom"]
DEFAULT_COMPLETION_CRITERIA: CompletionCriteriaKind = "files_written"
# Where the resolved criteria came from — drives CEO-facing gap / echo copy.
# ``text_inferred`` is retained only for historical gap-format strings; the resolver
# no longer produces it (检索与交付约束前置提案 B1).
CriteriaSource = Literal["explicit", "structured", "text_inferred"]

# Execution-class tool names (structural allow-list signal for B2 injection scope).
# Must stay aligned with ``code_execution_enabled_for`` / worker registry execution class.
_EXECUTION_TOOL_NAMES = frozenset({"code_execute", "test_run", "terminal"})

# D2: TypeScript landings require a real verify signal (not task-text inference).
_TYPESCRIPT_SUFFIXES = frozenset({".ts", ".tsx"})

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
# never resolve to ``code_verified`` from these hints (提案 B1).
_EXECUTION_TASK_HINTS = re.compile(
    r"(运行|启动|打开|安装|跑通|联调|验收|测试通过|"
    r"npm\s+(run|start)|pnpm\s+(run|start)|yarn\s+(run|start|dev)|"
    r"python\s+-m|uv\s+run|pip\s+run|cargo\s+run|go\s+run|进程)",
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


@dataclass(frozen=True)
class CompletionCriteria:
    kind: CompletionCriteriaKind
    description: str = ""


@dataclass(frozen=True)
class ResolvedCompletion:
    """Resolved batch-level criteria plus provenance for gap messaging / logging."""

    criteria: CompletionCriteria | None
    source: CriteriaSource | None = None


def parse_completion_criteria(raw: Any) -> CompletionCriteria | None:
    """Parse delegate ``completion_criteria``; ``None`` means no explicit enforcement."""
    if raw is None:
        return None
    if isinstance(raw, str):
        if raw in ("files_written", "code_verified", "custom"):
            return CompletionCriteria(kind=raw)  # type: ignore[arg-type]
        return CompletionCriteria(kind=DEFAULT_COMPLETION_CRITERIA)
    if isinstance(raw, dict):
        kind = raw.get("type") or raw.get("kind") or DEFAULT_COMPLETION_CRITERIA
        if kind not in ("files_written", "code_verified", "custom"):
            kind = DEFAULT_COMPLETION_CRITERIA
        desc = str(raw.get("description") or "")
        return CompletionCriteria(kind=kind, description=desc)  # type: ignore[arg-type]
    return CompletionCriteria(kind=DEFAULT_COMPLETION_CRITERIA)


def plan_suggests_code_verification(plan: RunPlan) -> bool:
    """True when any worker task/objective reads like run/open/install acceptance."""
    for node in plan.nodes:
        text = f"{node.task}\n{node.objective}".strip()
        if text and _EXECUTION_TASK_HINTS.search(text):
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


def validate_completion_against_forms(
    raw: Any,
    plan: RunPlan,
) -> str | None:
    """Reject ``files_written`` when every worker is ``form=prose`` (契约矛盾).

    Returns an error message for the CEO, or ``None`` when the combination is fine.
    """
    if raw is None:
        return None
    criteria = parse_completion_criteria(raw)
    if criteria is None or criteria.kind != "files_written":
        return None
    if not plan_all_workers_prose(plan):
        return None
    return (
        "契约矛盾：completion_criteria=files_written 要求至少一名 worker 落盘，"
        "但本批全部 worker 均为 deliverable.form=prose（纯文字、不授写文件工具）。"
        "改法：① 纯文字交付请省略 completion_criteria，或改用 code_verified（若需跑通验证）；"
        "② 若确需落盘，把对应 worker 的 deliverable.form 改为 files。"
    )


def validate_cold_start_explore_deliverables(
    plan: RunPlan,
    *,
    explicit_criteria: Any = None,
) -> str | None:
    """Hard-reject ``form=files`` / ``artifacts`` while cold-start explore is pending.

    Default explore path must use prose; project profile is written by the CEO via
    ``update_project_profile``, not by worker file landings. Explicit top-level
    ``completion_criteria`` of kind ``files_written`` is an intentional override
    (进阶：探索批也要落盘) — then file-landing deliverables are allowed.
    Returns CEO-facing error text, or ``None`` when the batch is fine.
    """
    if explicit_criteria is not None:
        parsed = parse_completion_criteria(explicit_criteria)
        if parsed is not None and parsed.kind == "files_written":
            return None
    for node in plan.nodes:
        d = node.deliverable
        if d is None:
            continue
        if d.form == "files" or bool(d.artifacts):
            return (
                "冷启动探索未完成：探路委派须用 deliverable.form=prose"
                "（禁止 form=files / artifacts）。"
                "项目画像由 CEO 调用 update_project_profile 写入；"
                "探索收尾（画像写入成功）后再用 form=files 做交付批。"
                "若本批确需落盘验收，请显式声明顶层 completion_criteria=files_written。"
            )
    return None


def plan_mentions_binary_artifact(plan: RunPlan) -> bool:
    """True when any worker task/objective reads like a binary / playable deliverable."""
    for node in plan.nodes:
        text = f"{node.task}\n{node.objective}".strip()
        if text and _BINARY_ARTIFACT_HINTS.search(text):
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
            "（与 tasks 同级，如 files_written / code_verified / "
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
    """Hard gate: resolved ``code_verified`` on a workspace with NO execution class.

    Fires for whatever ``resolve_completion_criteria`` will enforce at completion
    (同一谓词；B1 后绑定 criteria 仅来自显式声明 / 结构化 form·artifacts，文案启发
    只走软警告)。Capability truth is ``code_execution_enabled_for`` (the SAME
    predicate the worker registry uses). Returns the CEO-facing rejection message
    (with concrete ways out), or ``None`` when the combination is fine.
    """
    if not _resolved_code_verified(raw, plan):
        return None
    from agentcore.tools.builtin import code_execution_enabled_for

    if code_execution_enabled_for(backend):
        return None
    return (
        "无法按 code_verified 验收：本回合工作区为云端沙箱、未装配 code_execute / test_run"
        "（执行环境不可用），worker 写得了文件但运行不了代码，这条委派会空跑。出路："
        "① 需要真跑通 → 立即发 ask_user 卡（桌面在线时选项标 action=bind_local_folder），"
        "勿用纯文本询问；绑定完成后再委派；"
        "② 改为当前环境可交付的形态 → 落盘生成脚本 / 源文件 + 使用说明"
        "（deliverable.form=files，completion_criteria=files_written，任务文案不写"
        "「运行 / 跑通」类要求），并在收尾向用户显式标出「未运行验证」的交付缺口；"
        "③ 交付形态拿不准 → 先 ask_user 与用户对齐再委派。"
    )


def execution_capability_warning(
    raw: Any,
    plan: RunPlan,
    backend: Any,
) -> str | None:
    """Soft warning: binary-artifact deliverable smell with no execution class.

    Fires only when the hard gate did NOT (resolved criteria is not ``code_verified`` —
    e.g. explicit ``files_written`` on a run-flavoured task, or binary-artifact hints
    without run hints). Never blocks — the caller appends it to the delegate tool
    result so the CEO plans an honest deliverable (剩余启发只软警告，误报宁可漏不可错杀).
    """
    if _resolved_code_verified(raw, plan):
        return None  # hard gate owns this case
    if not (plan_suggests_code_verification(plan) or plan_mentions_binary_artifact(plan)):
        return None
    from agentcore.tools.builtin import code_execution_enabled_for

    if code_execution_enabled_for(backend):
        return None
    return (
        "[能力提示] 本回合执行环境未装配（云端沙箱，无 code_execute / test_run / terminal）："
        "任务文案涉及「运行 / 启动 / 生成二进制或可播放产物」，worker 只能写脚本 / 文件，"
        "无法真正运行或生成此类产物。收尾时请把交付缺口如实标给用户"
        "（如「脚本已落盘、未运行验证」），或立即发 ask_user 卡"
        "（桌面在线时 action=bind_local_folder，勿用纯文本询问）后重派。"
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
    if resolved.source == "explicit":
        return f"本批验收：{kind}（显式声明）"
    if resolved.source == "structured":
        return f"本批验收：{kind}（结构化交付声明）"
    return f"本批验收：{kind}"


def node_holds_execution_tools(spec: Any) -> bool:
    """True when the node is offered the execution-class tool set (structural).

    ``tools is None`` = unrestricted fail-safe default (all team tools, including
    execution class when the registry has them). A non-empty allow-list must
    intersect ``code_execute`` / ``test_run`` / ``terminal``. Never uses role text.
    """
    tools = getattr(spec, "tools", None)
    if tools is None:
        return True
    return bool(_EXECUTION_TOOL_NAMES.intersection(tools))


def should_inject_batch_acceptance(spec: Any, criteria: CompletionCriteria | None) -> bool:
    """Whether this worker should see batch ``completion_criteria`` in 交付物规格.

    Scope (提案 B2): resolved criteria present ∧ ``form=files`` ∧ holds execution
    tools — so research/prose peers are not nudged into redundant verification.
    """
    if criteria is None:
        return False
    deliverable = getattr(spec, "deliverable", None)
    if deliverable is None or getattr(deliverable, "form", None) != "files":
        return False
    return node_holds_execution_tools(spec)


def format_batch_acceptance_for_worker(criteria: CompletionCriteria) -> str:
    """One deliverable-spec line telling the worker the batch acceptance bar."""
    if criteria.kind == "files_written":
        return (
            "- 本批验收：files_written（至少一名持执行类工具的落盘 worker 须将产物"
            "写入工作区；你若负责落盘，请用 file_write / str_replace 完成）"
        )
    if criteria.kind == "code_verified":
        return (
            "- 本批验收：code_verified（至少一名 worker 须用 code_execute / test_run / "
            "terminal 跑通 verify 形态命令：tsc|typecheck|test|build 等且 exit 0；"
            "普通脚本/打印不算；你持有执行工具且交付为落盘文件时，请在收尾前完成验证）"
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
    """True when at least one ``test_run`` completed with zero failures/errors."""
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
        if "测试未通过" in content:
            continue
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


def _verify_gap_message() -> str:
    return (
        "尚无 worker 成功验证代码（须 code_execute / test_run / terminal 跑通 "
        "tsc|typecheck|test|build 等；落盘了 .ts/.tsx 时强制）"
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
) -> tuple[bool, list[str]]:
    """Return ``(ok, gaps)`` after all workers in a delegate batch finish.

    Explicit ``criteria`` is evaluated against every COMPLETED worker's real
    signals (``files_touched``, transcript tool results, handoff ``debrief``,
    prose ``content``)—not only workers with non-empty body text. A pure
    file_write / handoff finish with empty streamed content must still be
    checked; with no matching evidence the result is a gap, never a vacuous
    pass. ``criteria is None`` (omitted) remains unenforced for files/custom,
    but **TypeScript landings always require a verify signal** (D2 — structured
    from ``files_touched``, not task-text inference).
    """
    # Include all COMPLETED workers — empty body is a valid finish mode
    # (落盘 / handoff-only). Filtering on content.strip() used to drop them
    # and vacuous-pass when the filtered set was empty.
    completed = [s for s in results.values() if s.phase is RunPhase.COMPLETED]
    if not completed:
        return True, []

    gaps: list[str] = []
    if criteria is not None:
        if criteria.kind == "files_written":
            if not any(_worker_files_written(s) for s in completed):
                from agentcore.runtime.runs.serialize import format_file_landing_tools_slash

                tools = format_file_landing_tools_slash()
                gaps.append(f"尚无 worker 将产物写入工作区（需要 {tools} 落盘）")
        elif criteria.kind == "code_verified":
            if not any(_run_verified_in_transcript(s.transcript) for s in completed):
                gaps.append(_verify_gap_message())
        elif criteria.kind == "custom":
            # custom is intentionally not engine-verified. Never block completion on it —
            # a gap here used to mark successful delegates as unfinished. Prefer
            # files_written / code_verified / deliverable.artifacts instead.
            pass

    # D2: any .ts/.tsx landing → require verify even when criteria omitted /
    # files_written-only (catches「清单全绿但 tsc 不过」).
    if _batch_landed_typescript(completed) and not any(
        _run_verified_in_transcript(s.transcript or []) for s in completed
    ):
        msg = _verify_gap_message()
        if msg not in gaps:
            gaps.append(msg)

    if criteria is not None and criteria.kind == "custom" and not gaps:
        return True, []

    return (not gaps, gaps)


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


def gap_fingerprint(criteria_kind: str, gaps: list[str]) -> tuple[str, ...]:
    """Stable key for same-gap streak tracking across consecutive delegates."""
    return (criteria_kind, *gaps)


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
    head = "[系统提示] 完成条件未满足：" + "；".join(gaps)
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

    return "\n".join(parts)


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
                gaps.append(entry)
        debrief = state.debrief if isinstance(state.debrief, dict) else None
        if debrief and debrief.get("degraded"):
            text = DEGRADED_HANDOFF_WARNING
            if text not in seen_desc:
                seen_desc.add(text)
                gaps.append({"description": text, "reason": REASON_DEGRADED_HANDOFF})
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
        "\n### ⚠️ 契约缺口（请据缺口补派 / continue_from_run_id 续派，勿靠自觉扫清单）\n"
        "以下是各队员收尾后仍未对齐的声明交付物 / 交接缺口（含收敛强制收尾后无法再写文件"
        "留下的缺口，以及预算/超时掐断信号）。用 delegate / continue_from_run_id 补齐，"
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
            "可建议续派、绑定本地文件夹或 continue_from_run_id。"
        )
    if audit_off_with_token_budget:
        lines.append(
            "**【建议抽检】**本批未开 audit，且存在 token_budget 掐断缺口："
            "请在终稿提示用户抽检关键落盘文件 / 续派补齐，勿宣称已充分审计。"
        )
    return "\n".join(lines) + "\n"
