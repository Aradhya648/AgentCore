"""真·多模型辩手（Phase 3）——三元组身份 / 路由键 / 默认对阵 / 裁判选型。

权威定案：docs/03-AI核心/辩论编排设计.md §7.5。

- 身份 = model + origin(platform|byok) + provider_id(byok 必填)
- 路由键 = platform/{id} 或 {provider_id}/{id}
- 空身份 → 回退 turn 主模型；非空校验失败 → 硬失败（禁 silent）
- 裁判不要求中立、可与辩手同模；用户点名优先
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Literal

from agentcore.llm.profiles import PLATFORM_PROVIDER_SENTINEL
from agentcore.runtime.debate.types import DebateSide

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from agentcore.llm.catalog import ModelCatalog, ModelCatalogEntry
    from agentcore.llm.provider.protocol import LLMProvider
    from agentcore.runtime.debate.types import DebateConfig

ModelOrigin = Literal["platform", "byok"]


@dataclass(frozen=True)
class ModelIdentity:
    """目录对齐的模型三元组（空 model = 未指定）。"""

    model: str = ""
    origin: str = ""  # platform | byok | ""
    provider_id: str = ""

    def is_empty(self) -> bool:
        return not (self.model or "").strip()

    def normalized(self) -> ModelIdentity:
        mid = (self.model or "").strip()
        if not mid:
            return ModelIdentity()
        origin = (self.origin or "").strip().lower()
        provider_id = (self.provider_id or "").strip()
        if origin == "platform":
            provider_id = ""
        return ModelIdentity(model=mid, origin=origin, provider_id=provider_id)

    def route_key(self) -> str:
        """编成 ProviderRouter 路由键；空身份返回空串。"""
        ident = self.normalized()
        if ident.is_empty():
            return ""
        if ident.origin == "platform":
            return f"{PLATFORM_PROVIDER_SENTINEL}/{ident.model}"
        if ident.origin == "byok" and ident.provider_id:
            return f"{ident.provider_id}/{ident.model}"
        # 形状未齐——调用方应先 shape_error；此处不瞎猜裸串消歧。
        return ""

    def router_prefix(self) -> str:
        """ProviderRouter extras 注册键（platform 哨兵或 BYOK provider_id）。"""
        ident = self.normalized()
        if ident.is_empty():
            return ""
        if ident.origin == "platform":
            return PLATFORM_PROVIDER_SENTINEL
        return ident.provider_id if ident.origin == "byok" else ""

    def matches(self, other: ModelIdentity) -> bool:
        """参赛身份相等：优先比路由键；仅有裸 model 时比 id。"""
        a, b = self.normalized(), other.normalized()
        if a.is_empty() or b.is_empty():
            return False
        ka, kb = a.route_key(), b.route_key()
        if ka and kb:
            return ka == kb
        return a.model == b.model


def identity_from_side(side: DebateSide) -> ModelIdentity:
    return ModelIdentity(
        model=getattr(side, "model", "") or "",
        origin=getattr(side, "origin", "") or "",
        provider_id=getattr(side, "provider_id", "") or "",
    ).normalized()


def identity_shape_error(ident: ModelIdentity, *, where: str = "model") -> str:
    """同步形状校验（无目录）。空身份合法；非空须三元组齐。"""
    ident = ident.normalized()
    if ident.is_empty():
        return ""
    if ident.origin not in ("platform", "byok"):
        return (
            f"{where} 非空时须同时给出 origin（platform|byok）；"
            "禁止只填裸 model 字符串消歧。请补全三元组后重试。"
        )
    if ident.origin == "byok" and not ident.provider_id:
        return f"{where} origin=byok 时 provider_id 必填。请补全三元组后重试。"
    if not ident.route_key():
        return f"{where} 无法编成路由键（三元组不完整）。"
    return ""


def side_route_model(side: DebateSide, *, turn_model: str = "") -> str:
    """注入用模型：side 非空 → 路由键；空 → turn 主模型（可空）。"""
    ident = identity_from_side(side)
    if not ident.is_empty():
        key = ident.route_key()
        if key:
            return key
        # 形状残缺时不 silent 回退——由上游校验拦截；此处返回空让调用方可见。
        return ""
    return (turn_model or "").strip()


def priced_model_from_route(route_or_model: str) -> str:
    """计费用裸 model：剥 platform/ 或 BYOK provider_id/ 前缀；保留 doubao/ 等厂商键。"""
    raw = (route_or_model or "").strip()
    if "/" not in raw:
        return raw
    prefix, _, rest = raw.partition("/")
    if not rest:
        return raw
    if prefix == PLATFORM_PROVIDER_SENTINEL:
        return rest
    from agentcore.llm.pricing import _VENDOR_PREFIXES

    if prefix in _VENDOR_PREFIXES:
        return raw
    return rest


def _is_deepseek_family(model_id: str) -> bool:
    return "deepseek" in (model_id or "").lower()


def _entry_identity(entry: ModelCatalogEntry) -> ModelIdentity:
    return ModelIdentity(
        model=entry.id,
        origin=entry.origin,
        provider_id=entry.provider_id or "",
    ).normalized()


def _available_entries(catalog: ModelCatalog) -> list[ModelCatalogEntry]:
    return [e for e in catalog.models if e.available]


def candidate_from_entry(
    entry: ModelCatalogEntry, *, side_key: str = ""
) -> dict[str, Any]:
    """开赛卡 / 错误载荷候选行（model/origin/provider_id/label）。"""
    row: dict[str, Any] = {
        "model": entry.id,
        "origin": entry.origin,
        "provider_id": entry.provider_id or "",
        "label": (entry.display_name or entry.id).strip() or entry.id,
    }
    if side_key:
        row["side_key"] = side_key
    return row


def needs_mention_resolve(ident: ModelIdentity) -> bool:
    """model 非空但缺 origin（或 byok 缺 provider_id）→ 待消歧提及。"""
    ident = ident.normalized()
    if ident.is_empty():
        return False
    if ident.origin not in ("platform", "byok"):
        return True
    return ident.origin == "byok" and not ident.provider_id


def apply_identity_to_side(side: DebateSide, ident: ModelIdentity) -> DebateSide:
    ident = ident.normalized()
    return DebateSide(
        key=side.key,
        name=side.name,
        stance=side.stance,
        is_subject=bool(side.is_subject),
        model=ident.model,
        origin=ident.origin,
        provider_id=ident.provider_id,
    )


@dataclass(frozen=True)
class MentionResolveResult:
    """``resolve_model_mention`` 结果：唯一命中写 identity；否则带 candidates。"""

    ok: bool
    identity: ModelIdentity = field(default_factory=ModelIdentity)
    candidates: tuple[dict[str, Any], ...] = ()
    error: str = ""


def _strip_platform_prefix(mention: str) -> tuple[str, ModelOrigin | None]:
    """去「平台」前缀；命中则 prefer_origin=platform。"""
    raw = (mention or "").strip()
    if not raw:
        return "", None
    lower = raw.lower()
    for prefix in ("平台", "platform"):
        if raw.startswith(prefix):
            rest = raw[len(prefix) :].strip(" \t　:：-_")
            return rest, "platform"
        if lower.startswith(prefix.lower()) and prefix.isascii():
            rest = raw[len(prefix) :].strip(" \t　:：-_")
            return rest, "platform"
    return raw, None


def resolve_model_mention(
    mention: str,
    catalog: ModelCatalog,
    prefer_origin: ModelOrigin | None = None,
    *,
    side_key: str = "",
    where: str = "",
) -> MentionResolveResult:
    """口语提及 → 目录唯一三元组。

    去「平台」前缀、大小写不敏感匹配 id / display_name；DeepSeek 系走
    :func:`_is_deepseek_family`。唯一命中 → ok；0 / 多命中 → 结构化失败带 candidates。
    """
    text, inferred = _strip_platform_prefix(mention)
    prefer: ModelOrigin | None = prefer_origin or inferred
    if not text:
        return MentionResolveResult(
            ok=False,
            error="模型提及为空，无法消歧。",
            candidates=tuple(
                candidate_from_entry(e, side_key=side_key)
                for e in _available_entries(catalog)
            ),
        )

    available = _available_entries(catalog)
    pool = (
        [e for e in available if e.origin == prefer] if prefer else list(available)
    )
    text_l = text.lower()
    hits: list[ModelCatalogEntry] = []
    seen: set[tuple[str, str, str]] = set()

    def _add(entry: ModelCatalogEntry) -> None:
        key = (entry.id, entry.origin, entry.provider_id or "")
        if key in seen:
            return
        seen.add(key)
        hits.append(entry)

    for e in pool:
        if e.id.lower() == text_l:
            _add(e)
            continue
        if (e.display_name or "").strip().lower() == text_l:
            _add(e)
            continue
        if _is_deepseek_family(text) and (
            _is_deepseek_family(e.id) or _is_deepseek_family(e.display_name or "")
        ):
            _add(e)

    if len(hits) == 1:
        return MentionResolveResult(ok=True, identity=_entry_identity(hits[0]))

    label = where or (f"sides[`{side_key}`]" if side_key else "model")
    cand_src = hits if hits else (pool if pool else available)
    candidates = tuple(
        candidate_from_entry(e, side_key=side_key) for e in cand_src
    )
    if not hits:
        tip = (
            f"{label} 提及「{mention}」在可用目录中零匹配"
            + (f"（prefer={prefer}）" if prefer else "")
            + "。请从下列候选重填正式三元组；禁止再 ask_user 元问题。"
        )
    else:
        tip = (
            f"{label} 提及「{mention}」匹配到 {len(hits)} 个目录条目，无法唯一消歧。"
            "请从下列候选选定一条重填；禁止再 ask_user「是不是当前主模型」类元问题。"
        )
    lines = [
        f"  - {c['label']} · {c['origin']}/{c['model']}"
        + (f"（provider={c['provider_id']}）" if c.get("provider_id") else "")
        for c in candidates
    ]
    body = tip + ("\n候选：\n" + "\n".join(lines) if lines else "（目录无可选项）")
    return MentionResolveResult(ok=False, error=body, candidates=candidates)


def resolve_default_matchup(
    catalog: ModelCatalog,
) -> tuple[ModelIdentity, ModelIdentity] | None:
    """默认对阵：PLATFORM_MODELS[0] vs [1]；否则 1 平台 + BYOK DeepSeek；凑不齐 → None.

    ``prepare_debate_model_plan(cross_model=True)`` 在各方 model 皆空时真调本函数写回双方。
    """
    from agentcore.billing.preference import platform_model_allowlist

    available = _available_entries(catalog)
    platform_rows = [e for e in available if e.origin == "platform"]
    allowlist = platform_model_allowlist()
    # ① 平台 allowlist ≥2 → 按 PLATFORM_MODELS 顺序取前两名（非统一目录 models[] 前两项）。
    if len(allowlist) >= 2:
        by_id = {e.id: e for e in platform_rows}
        a, b = allowlist[0], allowlist[1]
        if a in by_id and b in by_id:
            return _entry_identity(by_id[a]), _entry_identity(by_id[b])
    if len(platform_rows) >= 2 and not allowlist:
        # 无显式 allowlist 时退化为平台目录前两行（稳定顺序来自 _platform_model_ids）。
        return _entry_identity(platform_rows[0]), _entry_identity(platform_rows[1])

    # ② 仅 1 个平台模型 + 已配 BYOK DeepSeek
    if len(platform_rows) >= 1:
        plat = platform_rows[0]
        for e in available:
            if e.origin == "byok" and _is_deepseek_family(e.id):
                return _entry_identity(plat), _entry_identity(e)
    return None


@dataclass(frozen=True)
class ModeratorResolution:
    identity: ModelIdentity
    same_model_debate: bool = False


def resolve_moderator_identity(
    *,
    catalog: ModelCatalog,
    debater_identities: Sequence[ModelIdentity],
    turn_main: ModelIdentity,
) -> ModeratorResolution:
    """裁判默认槽（未点名）：DeepSeek 系 → PLATFORM_MODELS 首个可用 → turn 主模型。

    **不要求中立、可与辩手同模**——不再因辩手已占用而跳过。``debater_identities``
    保留入参兼容调用方，不参与过滤。目录只剩一模型时 ``same_model_debate=True``。
    用户点名裁判走 :func:`prepare_debate_model_plan` 消歧，不经本函数。
    """
    from agentcore.billing.preference import platform_model_allowlist

    _ = debater_identities  # 兼容保留；不再「避开辩手」
    available = _available_entries(catalog)
    only_one = len(available) <= 1

    # ① DeepSeek 系（即使辩手已用）
    for e in available:
        if _is_deepseek_family(e.id):
            return ModeratorResolution(
                identity=_entry_identity(e),
                same_model_debate=only_one,
            )

    # ② PLATFORM_MODELS 第一可用
    allowlist = platform_model_allowlist()
    platform_by_id = {e.id: e for e in available if e.origin == "platform"}
    for mid in allowlist:
        entry = platform_by_id.get(mid)
        if entry is not None:
            return ModeratorResolution(
                identity=_entry_identity(entry),
                same_model_debate=only_one,
            )

    # 无 allowlist 命中时：平台目录第一可用
    for e in available:
        if e.origin == "platform":
            return ModeratorResolution(
                identity=_entry_identity(e),
                same_model_debate=only_one,
            )

    # ③ turn 主模型
    if not turn_main.is_empty():
        return ModeratorResolution(
            identity=turn_main.normalized(),
            same_model_debate=only_one if available else True,
        )

    # ④ 目录仅剩一项 / 空目录降级
    if available:
        return ModeratorResolution(
            identity=_entry_identity(available[0]),
            same_model_debate=only_one,
        )
    return ModeratorResolution(identity=ModelIdentity(), same_model_debate=True)


async def validate_identity_in_catalog(
    session: AsyncSession | None,
    user_id: str,
    ident: ModelIdentity,
    *,
    where: str = "model",
    catalog: ModelCatalog | None = None,
) -> str:
    """非空身份须过目录校验；失败返回错误文案，成功返回空串。"""
    from agentcore.llm.catalog import resolve_model_catalog, validate_model_choice

    ident = ident.normalized()
    shape = identity_shape_error(ident, where=where)
    if shape:
        return shape
    if ident.is_empty():
        return ""
    if catalog is None:
        if session is None:
            return f"{where} 无法校验目录（缺少 session）。"
        catalog = await resolve_model_catalog(session, user_id)

    want_provider = ident.provider_id if ident.origin == "byok" else None
    ok = any(
        e.id == ident.model
        and e.origin == ident.origin
        and e.provider_id == want_provider
        and e.available
        for e in catalog.models
    )
    if not ok and session is not None:
        ok = await validate_model_choice(
            session,
            user_id,
            ident.model,
            ident.origin,  # type: ignore[arg-type]
            ident.provider_id or None,
        )
    if not ok:
        return (
            f"{where} 不在可用目录或不具备凭据：{ident.origin}/{ident.model}"
            + (f"（provider={ident.provider_id}）" if ident.provider_id else "")
            + "。请改选目录内模型，禁止 silent 回退。"
        )
    return ""


async def prepare_debate_model_plan(
    config: DebateConfig,
    *,
    user_id: str,
    turn_model: str,
    turn_origin: str = "",
    turn_provider_id: str = "",
    session: AsyncSession | None = None,
    catalog: ModelCatalog | None = None,
    cross_model: bool = False,
) -> str:
    """开赛前：提及消歧 → 校验三元组 → 解析裁判（点名优先），写回 config。失败返回错误文案。

    - 口语提及（model 非空缺 origin）→ :func:`resolve_model_mention` 写回正式三元组
    - ``cross_model=True`` 且各方空 model → 真调 :func:`resolve_default_matchup`
    - 空且无旗标 = 同模型场（回退 turn main）
    - 消歧 0/多候选 → 硬失败，``config.model_candidates`` 挂目录候选
    - 裁判：``moderator_model`` 提及/三元组非空 → 消歧或校验写回；空 → 系统默认（可同模）
    """
    from agentcore.llm.catalog import resolve_model_catalog

    config.model_candidates = []

    if catalog is None and session is not None and user_id:
        catalog = await resolve_model_catalog(session, user_id)

    turn_main = ModelIdentity(
        model=turn_model, origin=turn_origin, provider_id=turn_provider_id
    ).normalized()

    # C · 默认对阵：旗标 + 各方空 model
    all_empty = all(identity_from_side(s).is_empty() for s in config.sides)
    if cross_model and all_empty:
        if catalog is None:
            return (
                "cross_model=true 但无法加载模型目录，凑不出默认对阵。"
                "请点名双方模型，或稍后重试。"
            )
        matchup = resolve_default_matchup(catalog)
        if matchup is None:
            config.model_candidates = [
                candidate_from_entry(e) for e in _available_entries(catalog)
            ]
            return (
                "cross_model=true 但目录凑不出默认跨模型对阵"
                "（需平台 allowlist≥2，或 1 平台 + BYOK DeepSeek）。"
                "请去配模型 / 加 BYOK，或点名双方模型；禁止 ask_user 元问题。"
            )
        a, b = matchup
        if len(config.sides) >= 2:
            config.sides[0] = apply_identity_to_side(config.sides[0], a)
            config.sides[1] = apply_identity_to_side(config.sides[1], b)

    # B · 提及消歧（写回正式三元组）
    for i, side in enumerate(config.sides):
        ident = identity_from_side(side)
        where = f"sides[`{side.key}`]"
        if not needs_mention_resolve(ident):
            continue
        if catalog is None:
            return (
                f"{where} 已填模型提及「{ident.model}」但无法加载目录消歧；"
                "请稍后重试，禁止 silent 回退 / ask_user 元问题。"
            )
        prefer: ModelOrigin | None = None
        if ident.origin in ("platform", "byok"):
            prefer = ident.origin  # type: ignore[assignment]
        result = resolve_model_mention(
            ident.model, catalog, prefer, side_key=side.key
        )
        if not result.ok:
            config.model_candidates = list(result.candidates)
            return result.error
        config.sides[i] = apply_identity_to_side(side, result.identity)

    # 校验各方（完整三元组；空=同模型场）
    for side in config.sides:
        ident = identity_from_side(side)
        where = f"sides[`{side.key}`]"
        shape = identity_shape_error(ident, where=where)
        if shape:
            return shape
        if ident.is_empty():
            continue
        if catalog is None and session is None:
            return (
                f"{where} 已填模型三元组但无法校验目录；"
                "请稍后重试，禁止 silent 回退。"
            )
        err = await validate_identity_in_catalog(
            session,
            user_id,
            ident,
            where=where,
            catalog=catalog,
        )
        if err:
            return err

    # 裁判：用户点名优先（提及消歧 / 完整三元组校验）；未点名 → 系统默认（可与辩手同模）
    mod_named = ModelIdentity(
        model=config.moderator_model or "",
        origin=config.moderator_origin or "",
        provider_id=config.moderator_provider_id or "",
    ).normalized()

    if not mod_named.is_empty():
        if needs_mention_resolve(mod_named):
            if catalog is None:
                return (
                    f"moderator_model 已填模型提及「{mod_named.model}」但无法加载目录消歧；"
                    "请稍后重试，禁止 silent 回退 / ask_user 元问题。"
                )
            prefer_mod: ModelOrigin | None = None
            if mod_named.origin in ("platform", "byok"):
                prefer_mod = mod_named.origin  # type: ignore[assignment]
            mod_result = resolve_model_mention(
                mod_named.model,
                catalog,
                prefer_mod,
                where="moderator_model",
            )
            if not mod_result.ok:
                config.model_candidates = list(mod_result.candidates)
                return mod_result.error
            mod = mod_result.identity.normalized()
        else:
            shape = identity_shape_error(mod_named, where="moderator_model")
            if shape:
                return shape
            if catalog is None and session is None:
                return (
                    "moderator_model 已填模型三元组但无法校验目录；"
                    "请稍后重试，禁止 silent 回退。"
                )
            mod_err = await validate_identity_in_catalog(
                session,
                user_id,
                mod_named,
                where="moderator_model",
                catalog=catalog,
            )
            if mod_err:
                return mod_err
            mod = mod_named
        config.moderator_model = mod.model
        config.moderator_origin = mod.origin
        config.moderator_provider_id = mod.provider_id
        config.moderator_route = mod.route_key() or (turn_model or "").strip()
        only_one = (
            catalog is not None and len(_available_entries(catalog)) <= 1
        )
        config.same_model_debate = only_one
        return ""

    debater_idents = [identity_from_side(s) for s in config.sides]
    effective = [
        (d if not d.is_empty() else turn_main) for d in debater_idents
    ]
    if catalog is not None:
        resolution = resolve_moderator_identity(
            catalog=catalog,
            debater_identities=effective,
            turn_main=turn_main,
        )
    else:
        resolution = ModeratorResolution(
            identity=turn_main, same_model_debate=True
        )

    mod = resolution.identity.normalized()
    config.moderator_model = mod.model
    config.moderator_origin = mod.origin
    config.moderator_provider_id = mod.provider_id
    config.moderator_route = mod.route_key() or (turn_model or "").strip()
    config.same_model_debate = bool(resolution.same_model_debate)
    return ""


async def ensure_debate_route_extras(
    llm: LLMProvider,
    identities: Sequence[ModelIdentity],
    *,
    user_id: str | None = None,
) -> None:
    """为辩手+裁判所需 prefix 注册 ProviderRouter extras（突破单 Worker extra）。

    平台身份一律挂 :func:`build_platform_provider`（按 request.model 取 key），
    不按「最后一个平台辩手」冻死单 key——跨 ``5.2`` / ``grok-4.5`` 辩论依赖此点。
    """
    from agentcore.billing.preference import is_platform_available
    from agentcore.llm.factory import build_platform_provider, build_provider
    from agentcore.llm.provider.router import ProviderRouter
    from agentcore.llm.resolve import resolve_provider_credentials

    if not isinstance(llm, ProviderRouter):
        return
    needed_byok: dict[str, ModelIdentity] = {}
    need_platform = False
    for ident in identities:
        ident = ident.normalized()
        if ident.is_empty():
            continue
        prefix = ident.router_prefix()
        if not prefix:
            continue
        if prefix == PLATFORM_PROVIDER_SENTINEL:
            need_platform = True
            continue
        if prefix in llm.available_prefixes:
            continue
        needed_byok[prefix] = ident

    if need_platform and is_platform_available():
        # 覆盖已有冻结 leaf（旧 build_turn_router / 误注册），保证一 key 一模型。
        llm.register(PLATFORM_PROVIDER_SENTINEL, build_platform_provider())

    if not needed_byok:
        return

    for prefix, _ident in needed_byok.items():
        if not user_id:
            continue
        from agentcore.db.base import async_session_factory

        async with async_session_factory() as session:
            creds = await resolve_provider_credentials(session, user_id, prefix)
        if creds is not None:
            llm.register(prefix, build_provider(creds))


def collect_debate_identities(config: DebateConfig, *, turn_model: str = "") -> list[ModelIdentity]:
    """辩手有效身份 + 裁判身份（供 router extras）。"""
    turn = ModelIdentity(model=turn_model).normalized()
    out: list[ModelIdentity] = []
    for side in config.sides:
        ident = identity_from_side(side)
        out.append(ident if not ident.is_empty() else turn)
    if (config.moderator_route or config.moderator_model or "").strip():
        out.append(
            ModelIdentity(
                model=config.moderator_model,
                origin=config.moderator_origin,
                provider_id=config.moderator_provider_id,
            ).normalized()
        )
    return out


def side_wire_fields(side: DebateSide) -> dict[str, Any]:
    """开赛卡 / debate_result sides 行：有三元组才带字段（absent 兼容旧向量）。"""
    row: dict[str, Any] = {
        "key": side.key,
        "name": side.name,
        "stance": side.stance,
        "is_subject": bool(side.is_subject),
    }
    ident = identity_from_side(side)
    if not ident.is_empty():
        row["model"] = ident.model
        if ident.origin:
            row["origin"] = ident.origin
        if ident.provider_id:
            row["provider_id"] = ident.provider_id
    return row
