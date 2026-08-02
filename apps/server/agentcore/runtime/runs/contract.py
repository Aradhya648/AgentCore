"""Contract gate: mechanical quality checks on a worker run's output (阶段2).

A worker's product is accepted only if it satisfies its node's delivery spec
(:class:`Deliverable`). 阶段2 第一刀做「机械校验」——看产出的*形*而非*质*：非空（系统
兜底，始终生效）、最短/最长长度、必含关键词、必备小标题、（声明
``output_format="json"`` 时）能否解析为 JSON、以及声明式 ``artifacts`` 路径清单相对
工作区的存在性对账。当 ``output_format=json`` 与 ``artifacts`` 同用时，JSON 可解析性
改验工作区文件（结构化文件通道），不再要求聊天正文是 JSON。``output_format=json`` 与
``required_sections``（Markdown 小标题语义）混用时跳过章节校验，避免自相矛盾的假失败。

交付形态对齐：文件形态交付（:func:`is_file_deliverable` — ``form=files`` /
``requires_files`` / ``artifacts``）的长度 / 关键词 / 章节检查读「正文 + 本 run 落盘
文件」——任一通道命中即满足，有效长度 = max(正文, 各文件)。产品在盘上时不再因正文只是
简报而假失败「缺章节 / 太短」；prose 交付保持只看正文。

网页接缝静态检查：同批落盘出现 HTML + CSS/JS 时，交叉校验 HTML class/id 与 CSS/JS
选择器命中率（未命中率超过阈值则 fail → ``contract.retry``）；普通文档交付不触发。

占位符 / 未核实内容扫描（定案乙）：内容类落盘（HTML / Markdown / …）检出骨架标记
（``400-XXX-XXXX``、``PLACEHOLDER``、``[占位]``、lorem ipsum 等）与自注（「示例数据」
「待核实」等）一律写入 :class:`ContractVerdict` 的 ``warnings``（不阻断验收、不占满
``contract.retry``）。字数 ``min_length`` / 必含词 ``must_contain`` 同为 soft。
代码文件豁免 TODO/XXX 习惯。建站链 ``web_quality`` / ``web_seam`` 硬闸与引用/书目硬闸不变。

引用 / 书目质量（台账接通时）：对内容类 ``artifact_contents`` 复用
:func:`~agentcore.runtime.verify.citation_quality_reworks`（与 chat ``finish_guard`` 同源）——
非法 ``#rN``、无绑定 GB/T ``[DCOP[J]`` 著录等 → fail → 合同返工。

判「写得好不好」的语义裁判（额外一次 LLM 调用）留作后续增强。

校验的后续处置（带反馈返工 / 按 ``strict`` 决定硬退或软提醒）在执行器里，本模块只产出结论
（:class:`ContractVerdict`）、给模型的修正说明与产出要求描述，保持纯函数、可独立单测。

→ 见设计: docs/03-AI核心/执行引擎架构设计.md §八（Run 模型）
"""

from __future__ import annotations

import fnmatch
import json
import re
from dataclasses import dataclass, field
from typing import Any

from agentcore.runtime.runs.placeholder_scan import (
    is_content_deliverable_path,
    needs_placeholder_scan,
    scan_placeholder_signals,
)
from agentcore.runtime.runs.types import Deliverable
from agentcore.runtime.runs.web_quality_scan import (
    needs_web_quality_scan,
    scan_web_quality,
)
from agentcore.runtime.runs.web_seam import (
    check_integrated_web_seam_failures,
    check_web_seam_failures,
    is_web_artifact_batch,
)
from agentcore.workspace._paths import strip_root_label_prefix

# Sandbox absolute paths models declare (``/workspace/…``) must compare as
# workspace-relative — same rewrite file tools use before the containment guard.
_ARTIFACT_ROOT_LABEL = "workspace"

# Handoff minimum when the node has downstream dependents (协作模式 handoff 门禁).
MIN_HANDOFF_SUMMARY_CHARS = 50
MIN_HANDOFF_KEY_POINTS = 2


@dataclass
class ContractVerdict:
    """Outcome of checking one output against its contract."""

    ok: bool
    failures: list[str] = field(default_factory=list)
    # Soft signals (e.g.「示例数据」「待核实」) — never flip ``ok`` by themselves.
    warnings: list[str] = field(default_factory=list)
    # Anti-slop / soft web-quality hits — flip ``ok`` for one rework shot, then the
    # executor demotes them to ``warnings`` (never hard-fail the run).
    soft_failures: list[str] = field(default_factory=list)
    # P1c visual critic critical findings — flip ``ok`` for up to 2 reworks, then
    # demote to warnings (partial). Populated by the executor after hard gates.
    visual_failures: list[str] = field(default_factory=list)


def is_file_deliverable(deliverable: Deliverable | None) -> bool:
    """Whether the deliverable's product lands as workspace files (not chat prose).

    ``form="files"`` (explicit), ``requires_files`` (must ``file_write``), or a non-empty
    ``artifacts`` list all mean the product is a file — so the contract's content checks
    (length / keyword / section) must read the landed files, not only the chat body
    (交付形态对齐: a paper written to disk with a terse chat note must not fail「缺章节 /
    太短」). Prose / unspecified deliverables keep body-only semantics.
    """
    return bool(
        deliverable is not None
        and (
            deliverable.form == "files"
            or deliverable.requires_files
            or deliverable.artifacts
        )
    )


def needs_file_contents(
    deliverable: Deliverable | None,
    *,
    landed_paths: list[str] | None = None,
) -> bool:
    """Whether :func:`check_contract` will consult landed-file text for this deliverable.

    Consumers that read file contents: the JSON file gate (``output_format="json"`` +
    ``artifacts``), the file-form content channel (length / keyword / section on a file
    deliverable), the web seam gate (HTML + CSS/JS in ``landed_paths``), the
    placeholder scan, and (when the executor passes ledger ids into
    :func:`check_contract`) the citation / bibliography gate on the same content
    surfaces. A file deliverable with only existence / ``requires_files`` rules needs
    no read unless the landed batch is a web artifact set or a content surface. The
    executor uses this to skip file I/O when the contract would ignore the contents
    anyway.
    """
    if landed_paths and is_web_artifact_batch(landed_paths):
        return True
    # Content surfaces: placeholder + citation/bibliography (ledger-connected) share
    # this load path.
    if landed_paths and needs_placeholder_scan(landed_paths):
        return True
    if deliverable is None:
        return False
    if deliverable.web_seam_scope:
        return True
    if deliverable.web_quality_scan and landed_paths and needs_web_quality_scan(landed_paths):
        return True
    if deliverable.web_quality_scan:
        return True
    if (
        deliverable.form == "files" or deliverable.requires_files
    ) and deliverable.artifacts:
        return True
    if deliverable.output_format == "json" and deliverable.artifacts:
        return True
    if deliverable.code_audit_gate:
        return True
    if not is_file_deliverable(deliverable):
        return False
    return bool(
        deliverable.min_length
        or deliverable.must_contain
        or deliverable.required_sections
    )


def _placeholder_hard_exempt_paths(
    deliverable: Deliverable | None,
    artifact_contents: dict[str, str] | None,
) -> list[str]:
    """Resolve deliverable-declared paths that skip hard placeholder failures."""
    if deliverable is None:
        return []
    if deliverable.placeholder_hard_exempt and artifact_contents:
        return [p for p in artifact_contents if p]
    return [
        p
        for p in (deliverable.placeholder_hard_exempt_artifacts or [])
        if isinstance(p, str) and p.strip()
    ]


def zero_files_gap_message(*, landing_failure_kind: str | None = None) -> str:
    """User/admin-facing zero-disk gap copy, attributed by real cause when known.

    Keeps the shared marker ``未把产物写入工作区`` so :func:`is_zero_files_gap` and
    delivery_status projection stay aligned. Does **not** invent new gap reason
    codes — callers keep ``files_not_landed``.
    """
    if landing_failure_kind == "channel_dead":
        return (
            "未把产物写入工作区：写盘通道不可用（local workspace channel dead / "
            "活性挂起），落盘工具已失败——请恢复工作区通道后重试，"
            "勿改用正文粘贴冒充落盘"
        )
    if landing_failure_kind == "write_failed":
        from agentcore.runtime.runs.serialize import format_file_landing_tools_slash

        tools = format_file_landing_tools_slash()
        return (
            "未把产物写入工作区：已尝试写盘但未成功落盘（工具失败），"
            f"请用 {tools} 修复后重写——"
            "此缺口来自写盘失败，而非「粘在回复正文」"
        )
    return (
        "未把产物写入工作区：交付物须用 file_write / str_replace / file_append "
        "或 code_execute / file_copy 落盘，而非粘在回复正文里"
    )


def check_contract(
    content: str,
    deliverable: Deliverable | None,
    *,
    files_written: int = 0,
    debrief: dict[str, Any] | None = None,
    workspace_paths: list[str] | None = None,
    artifact_contents: dict[str, str] | None = None,
    ledger_entries: list[dict[str, Any]] | None = None,
    citable_ids: frozenset[str] | set[str] | None = None,
    enforce_citations: bool = True,
    landing_failure_kind: str | None = None,
) -> ContractVerdict:
    """Check ``content`` against ``deliverable``; return a verdict + human reasons.

    The non-empty baseline always applies — an empty product is never acceptable,
    even with no deliverable (系统兜底，对应决策②). When a deliverable is given, its
    mechanical rules layer on top. Failure order is stable so feedback reads
    predictably.

    ``files_written`` is the count of workspace paths the run actually landed (from
    ``files_touched_from_transcript`` — successful file_write/append/str_replace/move/
    copy results AND ``code_execute`` sandbox write-backs). ``form=files`` /
    ``requires_files`` with zero successful landing becomes a soft ``warnings`` tip
    (甲⁺：不再契约 fail / 短写盘 pass). ``landing_failure_kind`` (optional)
    attributes the soft tip: ``channel_dead`` / ``write_failed`` vs paste framing.
    Stays a pure function (the caller derives the count / kind) so it remains
    trivially unit-testable.

    ``workspace_paths`` is the flat path index used to reconcile ``artifacts``
    patterns (exact / directory prefix / glob). Callers pass the live workspace
    listing unioned with this run's ``files_touched``; ``None`` / empty means the
    workspace looks empty for matching purposes.

    ``artifact_contents`` maps workspace paths → file text. When ``output_format=json``
    pairs with ``artifacts``, the JSON gate reads these texts (file channel) instead of
    requiring the chat body to be JSON. When the same map holds an HTML+CSS/JS web batch,
    the web seam gate cross-checks HTML class/id tokens against CSS/JS selectors. When it
    holds content surfaces (HTML / Markdown / …), the placeholder scan flags skeleton
    markers and soft self-notes as ``warnings`` (定案乙：不再 hard-fail). When
    ``ledger_entries`` is not ``None`` (turn evidence ledger connected; empty list
    still counts), content surfaces are also checked with
    :func:`~agentcore.runtime.verify.citation_quality_reworks` (same rules as chat
    ``finish_guard``) — unless ``enforce_citations=False`` (调研阶段 A：检索草案跳过
    成稿引用闸). Callers that cannot supply contents still get existence checks
    via ``artifacts``; parseability / seam / placeholder / citation checks are
    enforced when contents are given.

    交付形态对齐: for a FILE deliverable (:func:`is_file_deliverable` — ``form=files`` /
    ``requires_files`` / ``artifacts``) the same texts back the length / keyword / section
    checks, which then read the run's landed files ALONGSIDE the chat body — a section or
    keyword hit in either satisfies it, and the effective length is ``max(body, each
    file)`` (NOT concatenated). The executor loads them (matching ``artifacts`` when
    declared, else this run's ``files_touched``); check_contract stays a pure function.
    Empty / absent contents fall back to body-only (graceful when a read failed).

    Workers often finish with ``file_write`` + ``handoff`` and no streamed prose
    (``deliverable_only`` rolls back narration before non-terminal tools). The
    baseline therefore also accepts alternate product signals: workspace file writes
    (``files_written > 0``) or a usable ``handoff`` debrief (``debrief`` from
    ``debrief_from_transcript`` — summary / key_points / etc.).
    """
    text = content.strip()
    if not _has_product_signal(text, files_written, debrief, deliverable, artifact_contents):
        return ContractVerdict(ok=False, failures=["产出为空"])
    if deliverable is None:
        web_failures = check_web_seam_failures(artifact_contents)
        ph = scan_placeholder_signals(artifact_contents)
        cite_failures = (
            _artifact_citation_failures(
                artifact_contents,
                ledger_entries=ledger_entries,
                citable_ids=citable_ids,
            )
            if enforce_citations
            else []
        )
        failures = [*web_failures, *ph.failures, *cite_failures]
        if failures:
            return ContractVerdict(ok=False, failures=failures, warnings=ph.warnings)
        return ContractVerdict(ok=True, warnings=ph.warnings)

    exempt_paths = _placeholder_hard_exempt_paths(deliverable, artifact_contents)
    failures = []  # deliverable-specific failures (distinct from early-return above)
    soft_length_warnings: list[str] = []
    soft_keyword_warnings: list[str] = []
    # 交付形态对齐: a FILE deliverable's product lives on disk, so the content checks read
    # the run's landed files alongside the chat body. Prose deliverables (no file channel)
    # keep body-only semantics. Contents come from the caller via ``artifact_contents``;
    # empty / absent ⇒ body-only (graceful fallback when a read failed).
    file_texts: list[str] = []
    if is_file_deliverable(deliverable) and artifact_contents:
        file_texts = [t for t in artifact_contents.values() if t and t.strip()]
    # 有效长度 = max(正文, 各交付文件)，不拼接（避免正文+文件虚高绕过 min）。
    length = max([len(text), *(len(t) for t in file_texts)])
    # 定案乙：min_length / must_contain 一律 soft（不 fail、不占满 contract.retry）。
    if deliverable.min_length and length < deliverable.min_length:
        soft_length_warnings.append(
            f"篇幅提醒（软）：产出 {length} 字，少于要求的 {deliverable.min_length} 字"
        )
    if deliverable.must_contain:
        # Case-insensitive, mirroring required_sections' casefold match — the keyword
        # is a content requirement, not a literal-byte check, so casing must not flip
        # the soft tip. The reminder still shows the operator's original text.
        # 正文或任一交付文件命中即满足。
        haystacks = [content.casefold(), *(t.casefold() for t in file_texts)]
        for keyword in deliverable.must_contain:
            if keyword and not any(keyword.casefold() in h for h in haystacks):
                soft_keyword_warnings.append(
                    f"素材覆盖提醒（软）：未命中「{keyword}」——若有同级替代表达可保留并说明"
                )
    # required_sections = Markdown heading semantics. Skip when output_format=json to
    # avoid false failures from JSON field names stuffed into required_sections.
    # 章节在正文或任一交付文件中作为小标题出现即满足。
    if deliverable.output_format != "json":
        for section in deliverable.required_sections:
            if not section:
                continue
            if _has_section(content, section) or any(
                _has_section(t, section) for t in file_texts
            ):
                continue
            failures.append(f"缺少必备章节：{section}")
    if deliverable.output_format == "json":
        if deliverable.artifacts:
            failures.extend(
                _json_artifact_failures(
                    deliverable.artifacts,
                    workspace_paths or [],
                    artifact_contents,
                )
            )
        elif not _is_json(content):
            failures.append("产出不是可解析的 JSON")
    # 甲⁺：form=files / requires_files 零成功落盘 → soft tip（不 fail、不触发 write_pass）。
    zero_files_warnings: list[str] = []
    if (deliverable.requires_files or deliverable.form == "files") and files_written <= 0:
        zero_files_warnings.append(
            zero_files_gap_message(landing_failure_kind=landing_failure_kind)
        )
    # artifacts / artifact_dir 路径对账：有落盘即过；对不上降为 warnings（不阻断）。
    path_mismatch_warnings: list[str] = []
    if deliverable.artifacts:
        missing = missing_artifacts(deliverable.artifacts, workspace_paths or [])
        if missing:
            listed = "、".join(f"`{p}`" for p in missing)
            path_mismatch_warnings.append(f"声明的交付物路径未落盘：{listed}")
    # 案卷目录对账（与归属分键）：artifact_dir 不进 ownership；不对齐仅提醒。
    if deliverable.artifact_dir and deliverable.requires_files:
        from agentcore.runtime.runs.artifact_dir import normalize_artifact_dir

        dir_pat = f"{normalize_artifact_dir(deliverable.artifact_dir)}/"
        if dir_pat != "/" and not artifact_present(dir_pat, workspace_paths or []):
            path_mismatch_warnings.append(
                f"产物未写入案卷目录 `{dir_pat}`（建议落在此目录下，勿写到工作区根）"
            )
    # 网页接缝：同批 HTML+CSS/JS，或 ``web_seam_scope`` 终态整站复查。
    if deliverable.web_seam_scope:
        failures.extend(
            check_integrated_web_seam_failures(
                deliverable.web_seam_scope,
                artifact_contents,
                workspace_paths=workspace_paths,
            )
        )
    else:
        failures.extend(check_web_seam_failures(artifact_contents))
    # 占位符 / 未核实：内容类文件骨架标记 + 自注一律 warnings（定案乙：不硬拦）。
    # Internal coordination paths may declare skeleton exemption on the deliverable.
    ph = scan_placeholder_signals(artifact_contents, hard_exempt_paths=exempt_paths)
    failures.extend(ph.failures)
    # 引用 / 书目：与 chat finish_guard 同源；仅台账接通时扫内容类落盘。
    # 调研阶段 A（enforce_citations=False）跳过成稿引用闸。
    if enforce_citations:
        failures.extend(
            _artifact_citation_failures(
                artifact_contents,
                ledger_entries=ledger_entries,
                citable_ids=citable_ids,
            )
        )
    # code_audit 结构闸（L2b）：配套 *.audit.json 字段语义；与成篇硬门正交。
    if deliverable.code_audit_gate:
        from agentcore.runtime.runs.code_audit_gate import code_audit_json_failures

        failures.extend(
            code_audit_json_failures(
                artifacts=deliverable.artifacts,
                workspace_paths=workspace_paths or [],
                artifact_contents=artifact_contents,
            )
        )
    soft_failures: list[str] = []
    # 前端质量门禁（独立于 placeholder / web_seam）：硬=语法损坏+编造联系方式；软=anti-slop。
    if deliverable.web_quality_scan:
        wq = scan_web_quality(
            artifact_contents,
            soft_exempt=deliverable.web_quality_soft_exempt,
            soft_exempt_labels=deliverable.web_quality_soft_exempt_labels,
        )
        failures.extend(wq.failures)
        soft_failures.extend(wq.soft_failures)
    warnings = [
        *ph.warnings,
        *soft_length_warnings,
        *soft_keyword_warnings,
        *zero_files_warnings,
        *path_mismatch_warnings,
    ]
    # Soft web-quality hits flip ok so the executor can spend one rework shot;
    # after that shot the executor demotes them to warnings.
    ok = not failures and not soft_failures
    return ContractVerdict(
        ok=ok, failures=failures, warnings=warnings, soft_failures=soft_failures
    )


def missing_artifacts(patterns: list[str], workspace_paths: list[str]) -> list[str]:
    """Return artifact patterns with no match in ``workspace_paths`` (stable order)."""
    return [p for p in patterns if p and not artifact_present(p, workspace_paths)]


def _artifact_citation_failures(
    artifact_contents: dict[str, str] | None,
    *,
    ledger_entries: list[dict[str, Any]] | None,
    citable_ids: frozenset[str] | set[str] | None,
) -> list[str]:
    """Scan content-surface files with chat-side citation / bibliography rules.

    No-op when the turn evidence ledger is not connected (``ledger_entries is None``)
    and ``citable_ids is None``. Code / binary paths are skipped.
    """
    if artifact_contents is None:
        return []
    if ledger_entries is None and citable_ids is None:
        return []
    from agentcore.runtime.verify import citation_quality_reworks

    failures: list[str] = []
    for path, text in artifact_contents.items():
        if not path or not text or not text.strip():
            continue
        if not is_content_deliverable_path(path):
            continue
        for msg in citation_quality_reworks(
            text,
            citable_ids=citable_ids,
            ledger_entries=ledger_entries,
        ):
            failures.append(f"`{path}`：{msg}")
    return failures


# Citation failure lines from ``_artifact_citation_failures`` — `` `path`：… ``.
_CITATION_FAILURE_PATH_RE = re.compile(r"^`([^`]+)`\s*[：:]\s*(.*)$", re.DOTALL)


def is_citation_failure_message(text: str) -> bool:
    """True when ``text`` is a path-scoped citation / bibliography contract failure."""
    return bool(_CITATION_FAILURE_PATH_RE.match(str(text or "").strip()))


def partition_citation_failures(
    failures: list[str] | None,
) -> tuple[list[str], list[str]]:
    """Split contract failures into (citation, other). Stable order preserved."""
    cite: list[str] = []
    other: list[str] = []
    for raw in failures or []:
        text = str(raw)
        if is_citation_failure_message(text):
            cite.append(text)
        else:
            other.append(text)
    return cite, other


def paths_from_citation_failures(failures: list[str] | None) -> list[str]:
    """Extract workspace paths from path-scoped citation failure lines (stable, deduped)."""
    seen: set[str] = set()
    out: list[str] = []
    for raw in failures or []:
        match = _CITATION_FAILURE_PATH_RE.match(str(raw).strip())
        if not match:
            continue
        path = match.group(1).strip().replace("\\", "/")
        if not path or path in seen:
            continue
        seen.add(path)
        out.append(path)
    return out


def citation_rework_reread_paths(
    *,
    cite_failures: list[str] | None = None,
    checked_files: list[str] | None = None,
    artifacts: list[str] | None = None,
) -> list[str]:
    """Union of paths a citation rework pass should be allowed to re-read."""
    seen: set[str] = set()
    out: list[str] = []
    for group in (
        paths_from_citation_failures(cite_failures),
        checked_files or [],
        artifacts or [],
    ):
        for raw in group:
            path = (raw or "").strip().replace("\\", "/")
            if not path or path in seen:
                continue
            seen.add(path)
            out.append(path)
    return out


def strip_invalid_ledger_refs_from_surfaces(
    *,
    artifact_contents: dict[str, str] | None,
    body: str = "",
    citable_ids: frozenset[str] | set[str] | None,
) -> tuple[dict[str, str] | None, str, list[str]]:
    """Strip illegal ``#rN`` from content-surface artifacts and optional body.

    Reuses :func:`~agentcore.runtime.citations.invalid_ledger_ref_ids` /
    :func:`~agentcore.runtime.citations.strip_invalid_ledger_refs`. Returns
    ``(new_artifacts, new_body, stripped_ids)`` — ``stripped_ids`` is the sorted
    union of invalid ids found; empty means nothing changed (callers skip rewrite).
    """
    from agentcore.runtime.citations import (
        invalid_ledger_ref_ids,
        strip_invalid_ledger_refs,
    )

    if citable_ids is None:
        return artifact_contents, body, []

    bad: set[str] = set()
    if body:
        bad.update(invalid_ledger_ref_ids(body, citable_ids))
    if artifact_contents:
        for path, text in artifact_contents.items():
            if not path or not text or not text.strip():
                continue
            if not is_content_deliverable_path(path):
                continue
            bad.update(invalid_ledger_ref_ids(text, citable_ids))
    if not bad:
        return artifact_contents, body, []

    new_body = strip_invalid_ledger_refs(body, bad) if body else body
    new_arts: dict[str, str] | None = artifact_contents
    if artifact_contents:
        new_arts = {}
        for path, text in artifact_contents.items():
            if (
                path
                and text
                and text.strip()
                and is_content_deliverable_path(path)
            ):
                new_arts[path] = strip_invalid_ledger_refs(text, bad)
            else:
                new_arts[path] = text
    return new_arts, new_body, sorted(bad)


def format_cite_upgrade_feedback(
    cite_failures: list[str],
    *,
    checked_files: list[str] | None = None,
) -> str:
    """Phase-B light-repair prompt after auto-strip still leaves cite/bib issues.

    Instructs removing unverified ``#rN`` / bibliography claims or softening them
    to「待核实」— does **not** encourage ``read_url`` / broad search / deep_read.
    """
    if not cite_failures:
        return ""
    items = "\n".join(f"- {f}" for f in cite_failures)
    coverage = ""
    if checked_files:
        listed = "、".join(f"`{p}`" for p in checked_files)
        coverage = f"\n（检查通道：落盘文件 {listed}）"
    return (
        "【引用短修·阶段 B】自动剥离非法 #rN 后仍有引用/书目问题："
        f"\n{items}{coverage}\n\n"
        "请就地短修后 handoff（禁止广搜、深读链接、整篇重开）：\n"
        "去掉未核实的 #rN 与书目著录式断言，或改成标题+URL 线索 / 显式「待核实」弱表述；"
        "勿把未入成稿可引用集的编号写成已证事实。\n"
        "可用 str_replace 改落盘文件。不要道歉、不要另起无关长文。"
    )


def artifact_present(pattern: str, workspace_paths: list[str]) -> bool:
    """Whether ``pattern`` (exact path / directory / glob) hits any workspace path."""
    return bool(matching_artifact_paths(pattern, workspace_paths))


def _normalize_artifact_relpath(path: str) -> str:
    """Workspace-relative POSIX form for artifact pattern / index comparison.

    Models often declare sandbox absolutes (``/workspace/index.html``) while
    ``index_files`` / successful writes expose relative paths (``index.html``).
    A bare ``lstrip("./")`` turns ``/workspace/…`` into ``workspace/…``, which
    never equals the relative index entry — false「未落盘」. Strip the root
    label first (same primitive as file-tool path rescue), then drop ``./``.
    """
    raw = path.replace("\\", "/").strip()
    if not raw:
        return ""
    stripped = strip_root_label_prefix(raw, _ARTIFACT_ROOT_LABEL)
    # Bare ``/workspace`` → ``.``; treat as empty (no matchable file path).
    if stripped in (".", ""):
        return ""
    return stripped.lstrip("./")


def matching_artifact_paths(pattern: str, workspace_paths: list[str]) -> list[str]:
    """Workspace paths matching ``pattern`` (exact / directory prefix / glob), stable order."""
    pat = _normalize_artifact_relpath(pattern)
    if not pat:
        return []
    normalized = [_normalize_artifact_relpath(p) for p in workspace_paths if p]
    hits: list[str] = []
    for p in normalized:
        if not p:
            continue
        if pat.endswith("/"):
            prefix = pat
            bare = pat.rstrip("/")
            if p == bare or p.startswith(prefix):
                hits.append(p)
        elif any(ch in pat for ch in "*?["):
            if fnmatch.fnmatch(p, pat) or fnmatch.fnmatch(p.rsplit("/", 1)[-1], pat):
                hits.append(p)
        elif p == pat or p.endswith("/" + pat):
            hits.append(p)
    return hits


def _json_artifact_failures(
    patterns: list[str],
    workspace_paths: list[str],
    artifact_contents: dict[str, str] | None,
) -> list[str]:
    """Failures when structured JSON must land in artifact files (not chat).

    Existence is reported separately by ``missing_artifacts``. When contents are
    supplied, each present pattern must have at least one matching path whose text
    parses as JSON. When contents are omitted, parseability is not checked here
    (caller may only have a path index).
    """
    if artifact_contents is None:
        return []
    failures: list[str] = []
    # Normalize content keys the same way as path matching.
    by_norm = {
        _normalize_artifact_relpath(k): v for k, v in artifact_contents.items() if k
    }
    by_norm.pop("", None)
    for pattern in patterns:
        if not pattern:
            continue
        matches = matching_artifact_paths(pattern, workspace_paths)
        if not matches:
            continue  # missing_artifacts already covers absence
        parsed_ok = False
        unread: list[str] = []
        bad: list[str] = []
        for path in matches:
            if path not in by_norm:
                unread.append(path)
                continue
            if _is_json(by_norm[path]):
                parsed_ok = True
                break
            bad.append(path)
        if parsed_ok:
            continue
        if bad:
            listed = "、".join(f"`{p}`" for p in bad[:3])
            failures.append(f"交付物文件不是可解析的 JSON：{listed}")
        elif unread:
            listed = "、".join(f"`{p}`" for p in unread[:3])
            failures.append(f"交付物文件无法读取以校验 JSON：{listed}")
    return failures


# Format-only failures eligible for one in-place light repair (缺章节).
# 定案乙：min_length / must_contain 已降 soft，不再进 failures / light_repair。
# Placeholders, web seam, empty product, missing files, JSON parse, etc. stay on full retry.
_FORMAT_REPAIR_SECTION_PREFIX = "缺少必备章节："
_FORMAT_REPAIR_KEYWORD_PREFIX = "缺少必须包含的内容："  # legacy residual only
_FORMAT_REPAIR_TOO_SHORT_MARKER = "字，少于要求的"  # legacy residual only


def is_format_repairable(verdict: ContractVerdict) -> bool:
    """True when every failure is a format backfill (primarily missing sections).

    Used by the executor to try one cheap in-place completion before a full
    ``contract.retry`` that re-opens investigation. Mixed or non-format failures
    (网页接缝 / 网页质量 / 空产出 / JSON …) return False. 定案乙后字数 / 必含词
    不再出现在 ``failures``；保留 keyword/short markers 仅兼容遗留 verdict。
    """
    if verdict.ok or not verdict.failures or verdict.soft_failures or verdict.visual_failures:
        return False
    for failure in verdict.failures:
        text = str(failure).strip()
        if text.startswith(_FORMAT_REPAIR_SECTION_PREFIX):
            continue
        if text.startswith(_FORMAT_REPAIR_KEYWORD_PREFIX):
            continue
        if _FORMAT_REPAIR_TOO_SHORT_MARKER in text:
            continue
        return False
    return True


def format_light_repair_feedback(
    verdict: ContractVerdict,
    *,
    prior_content: str,
    checked_files: list[str] | None = None,
) -> str:
    """Correction prompt for one format-only light repair (no re-investigation).

    Carries the prior deliverable so the model backfills missing sections / length
    in place instead of restarting research. Investigation tools stay withheld by
    the executor for this pass.
    """
    if verdict.ok or not verdict.failures:
        return ""
    items = "\n".join(f"- {f}" for f in verdict.failures)
    coverage = ""
    if checked_files:
        listed = "、".join(f"`{p}`" for p in checked_files)
        coverage = (
            f"\n（检查通道：回复正文 + 落盘文件 {listed}；"
            "请在对应文件或正文就地补全。）"
        )
    prior = (prior_content or "").strip()
    prior_block = (
        f"\n\n【上一版交付·请就地补全，勿重写无关部分】\n{prior}"
        if prior
        else ""
    )
    return (
        "你上一次的产出只差格式补全（缺章节 / 篇幅不足 / 缺关键词），"
        f"不必重新调查：\n{items}{coverage}{prior_block}\n\n"
        "请对已落盘文件用 str_replace（或局部 file_append 填骨架空位）就地补齐后 "
        "handoff；优先以写回执 artifact manifest 验真，勿为空转反复 file_read "
        "自产物正文。"
        "不要重新检索、不要道歉、不要附带说明。"
    )


# Shared marker for zero-landing soft tips (contract warnings / delivery projection).
# 甲⁺：零落盘已降为 soft warning，不再进 failures，故不再驱动 write_pass。
_ZERO_FILES_GAP_MARKER = "未把产物写入工作区"


def is_zero_files_gap(verdict: ContractVerdict) -> bool:
    """True when failures still carry a hard zero-disk gap (legacy / residual).

    甲⁺：``check_contract`` puts zero-landing into ``warnings`` only, so this
    returns False for current verdicts and write_pass is not triggered.
    """
    if verdict.ok or not verdict.failures:
        return False
    return any(_ZERO_FILES_GAP_MARKER in str(f) for f in verdict.failures)


def format_write_pass_feedback(verdict: ContractVerdict) -> str:
    """Correction prompt for one short write-to-disk pass (no re-investigation)."""
    items = "\n".join(f"- {f}" for f in (verdict.failures or []))
    return (
        "你尚未把产物写入工作区。本轮是【短写盘 pass】——工具面已收窄为写盘/handoff："
        f"\n{items}\n\n"
        "请立即用 file_write / str_replace / file_append（或等价落盘）把产物写进工作区，"
        "然后调用 handoff。"
        "禁止重新调查、禁止全仓巡读、禁止只把内容贴在回复正文里。"
    )


def has_salvageable_half_product(
    content: str,
    files_touched: list[str] | None,
    debrief: dict[str, Any] | None = None,
) -> bool:
    """True when there is half-finished work worth summarizing / salvage.

    Empty body ∧ zero disk ∧ no qualified brief → not salvageable (skip empty
    ``degraded_synth`` / meaningless finalize LLM).
    """
    if (content or "").strip():
        return True
    if files_touched:
        return True
    return debrief_meets_minimum(debrief)


def transcript_has_tool_inventory(messages: list[Any] | tuple[Any, ...] | None) -> bool:
    """True when the transcript holds at least one successful non-empty tool result.

    Used by force-finalize: investigation-only workers may have zero prose / disk /
    brief yet still have readable tool inventory worth one salvage LLM round.
    Failed tool messages (``<!--agentcore:tool_failed-->`` trailer) do **not** count —
    otherwise unproductive all-fail loops would burn a useless salvage call.
    Does **not** widen :func:`has_salvageable_half_product` (keeps degraded_synth
    from minting empty briefs off tool chatter alone).
    """
    if not messages:
        return False
    from agentcore.runtime.engine.tool_exec import TOOL_FAILED_MARKER

    for msg in messages:
        if getattr(msg, "role", None) != "tool":
            continue
        content = getattr(msg, "content", None)
        text = str(content) if content is not None else ""
        if not text.strip():
            continue
        if TOOL_FAILED_MARKER in text:
            continue
        return True
    return False


def should_attempt_force_finalize_salvage(
    content: str,
    files_touched: list[str] | None,
    debrief: dict[str, Any] | None = None,
    *,
    messages: list[Any] | tuple[Any, ...] | None = None,
) -> bool:
    """Whether force_finalize should spend an LLM salvage round.

    Half-product (body / disk / brief) **or** non-empty tool inventory in
    ``messages``. Empty everything → skip (``force_finalize_skipped_empty``).
    """
    if has_salvageable_half_product(content, files_touched, debrief):
        return True
    return transcript_has_tool_inventory(messages)


def format_feedback(
    verdict: ContractVerdict, *, checked_files: list[str] | None = None
) -> str:
    """Render a verdict's failures as a correction instruction for the retry.

    This is the worker's single rework shot, so it's told to spend it on the
    product itself — emit the complete corrected output, no meta-commentary —
    rather than burning the turn on an apology or an explanation.

    Soft ``warnings`` (未核实 / 示例自注) are appended when present so the retry
    prompt also carries handoff-style reminders; warnings alone never produce a
    retry instruction (``ok`` stays true — caller may surface them via
    :func:`format_soft_reminders`). Soft ``soft_failures`` (anti-slop) and
    ``visual_failures`` (P1c critic) do trigger a retry and are listed alongside
    hard failures.

    ``checked_files`` (交付形态对齐: 标注检查通道) lists the run's landed files whose text
    this contract check covered alongside the chat body, so the worker knows WHERE the
    check looked and补进对应文件 / 正文, instead of assuming it must paste the product into
    chat. Omitted (prose deliverable) ⇒ no channel note (body-only check).
    """
    issues = [*verdict.failures, *verdict.soft_failures, *verdict.visual_failures]
    if verdict.ok or not issues:
        return ""
    items = "\n".join(f"- {f}" for f in issues)
    soft = ""
    if verdict.warnings:
        soft_items = "\n".join(f"- {w}" for w in verdict.warnings)
        soft = f"\n另有未阻断提醒（请一并处置或交接说明）：\n{soft_items}"
    coverage = ""
    if checked_files:
        listed = "、".join(f"`{p}`" for p in checked_files)
        coverage = (
            f"\n（本次契约检查的对象：回复正文 + 本次落盘文件 {listed}；"
            "章节/关键词在其中任一命中即算满足，篇幅按正文与各文件长度的最大值计——"
            "请把要补的内容写进对应文件或正文。）"
        )
    return (
        f"你上一次的产出未达到以下要求：\n{items}{soft}{coverage}\n"
        "请直接输出修正后的【完整最终产出】（补齐上述差距，其余内容保持原样），"
        "不要解释、不要道歉、不要附带任何说明文字。"
    )


def format_interrupted_pass_note() -> str:
    """Prefix for a retry whose previous pass died on an LLM transport failure.

    Without it the worker reads a bare 「产出为空」 as its own authoring failure —
    观测到的真实回归: 一次断流后 worker 的 reasoning 变成「上一轮我写空了」，于是它
    不重写正文、只是又调了一次 handoff，被空交付门禁挡回，白烧一轮。The pass's
    finish reason (ERROR / DEGRADED) is the executor's only reliable signal that
    the round never came back, so it — not the verdict — decides this note.
    """
    return (
        "[系统提示] 上一轮的模型响应在传输中被中断（网络 / 上游断流），"
        "系统只收到片段甚至完全没收到正文——下面的契约判定是基于这份残缺产出，"
        "不代表你上一轮写得不好。请把本轮正文完整重写一遍"
        "（此前已完成的调查结论直接复述，不必重新检索）；"
        "不要只调用 handoff 交空简报，也不要为此道歉或解释。"
    )


def format_soft_reminders(verdict: ContractVerdict) -> str:
    """Render soft contract warnings as a handoff-style reminder (never a hard fail).

    Empty when there are no ``warnings``. Safe to attach to debrief / CEO notes without
    flipping acceptance.
    """
    if not verdict.warnings:
        return ""
    items = "\n".join(f"- {w}" for w in verdict.warnings)
    return (
        f"契约软提醒（未阻断验收，请 worker / CEO 确认处置）：\n{items}"
    )


def describe_deliverable(deliverable: Deliverable | None) -> str:
    """Render a deliverable as up-front requirements stated in the worker's prompt."""
    if deliverable is None:
        return ""
    lines: list[str] = []
    if deliverable.name:
        lines.append(f"交付物：{deliverable.name}")
    if deliverable.form == "prose":
        lines.append("- 交付形态：纯文字（正文直接交付，不要落盘）")
    elif deliverable.form == "files":
        lines.append("- 交付形态：落盘文件（必须 file_write 写入工作区）")
    # Markdown section headings and JSON are mutually exclusive acceptance shapes.
    if deliverable.output_format == "json":
        if deliverable.artifacts and deliverable.form != "prose":
            lines.append(
                "- 产出必须是可解析的 JSON，写入声明的交付物路径"
                "（不要只贴在回复正文；契约验文件存在 + 可解析）"
            )
        else:
            lines.append("- 产出必须是可解析的 JSON")
    elif deliverable.required_sections:
        lines.append(
            "- 必须包含这些章节（用小标题）：" + "、".join(deliverable.required_sections)
        )
        # 验收骨架与 contract 同源：把 required_sections 直接铺成 Markdown 小标题骨架，
        # 避免 worker 只看到「必须包含」枚举却在正文里用错标题 → contract.retry。
        skeleton = "\n".join(f"## {section}\n" for section in deliverable.required_sections)
        lines.append("- 建议正文骨架（小标题须与上列一致，可在节内自由展开）：\n" + skeleton)
    if deliverable.must_contain:
        lines.append("- 建议覆盖（软）：" + "、".join(deliverable.must_contain))
    if deliverable.min_length:
        lines.append(f"- 篇幅不少于 {deliverable.min_length} 字")
    # prose form never surfaces file-landing requirements (even if a stale flag slipped in).
    if deliverable.form != "prose":
        if deliverable.artifact_dir:
            lines.append(
                f"- 建议案卷落盘目录：`{deliverable.artifact_dir}/`（系统约定；你只定文件名，"
                "建议写入此目录，勿写到工作区根或其他路径）"
            )
        if deliverable.artifacts:
            # Directory-only gate already covered by artifact_dir line — skip redundant
            # listing when artifacts is exactly the dir prefix.
            dir_prefix = (
                f"{deliverable.artifact_dir.rstrip('/')}/" if deliverable.artifact_dir else ""
            )
            listed_paths = [
                p
                for p in deliverable.artifacts
                if p
                and (
                    not dir_prefix
                    or (
                        p.replace("\\", "/").rstrip("/") + "/" != dir_prefix
                        and p.replace("\\", "/") != dir_prefix.rstrip("/")
                    )
                )
            ]
            if listed_paths:
                listed = "、".join(f"`{p}`" for p in listed_paths)
                lines.append(f"- 建议把以下交付物路径写入工作区（可用目录或通配）：{listed}")
            elif not deliverable.artifact_dir:
                listed = "、".join(f"`{p}`" for p in deliverable.artifacts)
                lines.append(f"- 建议把以下交付物路径写入工作区（可用目录或通配）：{listed}")
        elif deliverable.requires_files:
            lines.append(
                "- 必须调用 file_write / str_replace / file_append 把产物写进工作区"
                "（成品是落盘文件，不能只贴在回复正文里）"
            )
    if deliverable.code_audit_gate:
        lines.append(
            "- 须另交配套 `*.audit.json`（findings：severity/verification/verdict/evidence；"
            "高须 trigger_path；安全类或高须 reachability）；"
            "未读全/待核实不得标中+；全量 tsc/pytest 超时不得标中+；结构闸硬拒违规"
        )
    if deliverable.strict:
        lines.append("- 契约严格模式：返工后仍不达标将判定本节点失败（非软提醒）")
    return "\n".join(lines)


def _has_product_signal(
    text: str,
    files_written: int,
    debrief: dict[str, Any] | None,
    deliverable: Deliverable | None,
    artifact_contents: dict[str, str] | None,
) -> bool:
    """Whether the run has any non-empty product channel (body / disk / handoff).

    File deliverables also accept non-empty declared artifact texts on disk — so a
    ``file_write`` + empty streamed body (``deliverable_only``) does not false-fail
    「产出为空」 when the contract loaded the landed file contents.
    """
    if text or files_written > 0 or debrief is not None:
        return True
    if not is_file_deliverable(deliverable) or not artifact_contents:
        return False
    if deliverable and deliverable.artifacts:
        for pattern in deliverable.artifacts:
            for path in matching_artifact_paths(pattern, list(artifact_contents.keys())):
                if (artifact_contents.get(path) or "").strip():
                    return True
        return False
    return any((t or "").strip() for t in artifact_contents.values())


def debrief_meets_minimum(debrief: dict[str, Any] | None) -> bool:
    """True when a handoff brief meets the downstream-gate information floor."""
    if not debrief:
        return False
    summary = str(debrief.get("summary") or "").strip()
    if len(summary) >= MIN_HANDOFF_SUMMARY_CHARS:
        return True
    raw_points = debrief.get("key_points") or []
    if isinstance(raw_points, str):
        raw_points = [raw_points]
    points = [str(p).strip() for p in raw_points if str(p).strip()]
    return len(points) >= MIN_HANDOFF_KEY_POINTS


def format_handoff_feedback(*, present_but_thin: bool = False) -> str:
    """Correction instruction that forces one handoff (or a richer one) for downstream."""
    if present_but_thin:
        return (
            "你提交的 handoff 交接简报信息量不足（下游队员要靠它接手）。"
            f"请重新调用 handoff：summary 至少 {MIN_HANDOFF_SUMMARY_CHARS} 字，"
            f"或提供不少于 {MIN_HANDOFF_KEY_POINTS} 条具体 key_points"
            "（文件路径 / 关键决定 / 数字，别空泛）。"
            "调用 handoff 即收尾；不要只写正文不交简报。"
        )
    return (
        "你有下游队员依赖本次交接，但尚未调用 handoff。"
        "请在本轮调用 handoff 提交交接简报："
        f"summary 至少 {MIN_HANDOFF_SUMMARY_CHARS} 字，"
        f"或提供不少于 {MIN_HANDOFF_KEY_POINTS} 条具体 key_points"
        "（文件路径 / 关键决定 / 数字）。调用即代表收尾完成。"
    )


def synthesize_debrief(
    content: str,
    files_touched: list[str],
) -> dict[str, Any]:
    """Engine-built degraded debrief when a required handoff is still missing.

    Marked ``degraded=True`` so CEO / downstream know it is a fallback, not author intent.
    """
    parts: list[str] = []
    prose = content.strip()
    if prose:
        parts.append(prose[:200])
    if files_touched:
        parts.append("已落盘：" + "、".join(files_touched[:8]))
    summary = "；".join(parts) or "（引擎降级合成：无正文与落盘记录）"
    key_points = [f"文件：{p}" for p in files_touched[:4]] if files_touched else []
    out: dict[str, Any] = {"summary": summary, "degraded": True}
    if key_points:
        out["key_points"] = key_points
    return out


def node_has_dependents(plan: Any, run_id: str) -> bool:
    """True when any plan node lists ``run_id`` in its ``depends_on``."""
    nodes = getattr(plan, "nodes", None) or []
    return any(run_id in (getattr(n, "depends_on", None) or []) for n in nodes)


def _has_section(content: str, section: str) -> bool:
    """Whether ``content`` carries ``section`` as a heading-like line.

    Accepts a markdown heading (``# 结论``), a bold line (``**结论**``), or a
    labelled line (``结论：…``) — the shapes a model actually uses for a section —
    rather than any incidental mention, so the check means structure not keyword.
    """
    target = section.strip().casefold()
    if not target:
        return True
    for raw in content.splitlines():
        line = raw.strip()
        low = line.casefold()
        if line.startswith("#") and target in low:
            return True
        if line.startswith("**") and line.endswith("**") and target in low:
            return True
        if low.startswith(target) and low[len(target) :].lstrip()[:1] in ("：", ":"):
            return True
    return False


def _is_json(content: str) -> bool:
    """Whether ``content`` (optionally inside a ```json fence) parses as JSON."""
    try:
        json.loads(_strip_code_fence(content.strip()))
    except (ValueError, TypeError):
        return False
    return True


def _strip_code_fence(text: str) -> str:
    """Drop a surrounding ``` / ```json fence if present, else return as-is."""
    if not text.startswith("```"):
        return text
    body = text[3:]
    newline = body.find("\n")
    if newline != -1 and body[:newline].strip().casefold() in ("", "json"):
        body = body[newline + 1 :]
    if body.rstrip().endswith("```"):
        body = body.rstrip()[:-3]
    return body.strip()
