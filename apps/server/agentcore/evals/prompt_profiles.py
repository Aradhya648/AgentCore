"""eval 侧的 prompt 变体注册表（方向①）：把命名变体解析成运行期注入的 :class:`PromptProfile`.

用例用 ``EvalCase.prompt_profile``（一个名字）声明跑哪个变体；harness 经
:func:`resolve_prompt_profile`
查表、在本例运行期 ``use_profile`` 注入。``seed_lint`` 用 :data:`PROFILE_NAMES` 校验名字是否存在
（写错立刻挂）。机制细节见 [`runtime/prompt_profile.py`](../runtime/prompt_profile.py)。

**v1 内容**：``baseline``（恒等，与生产逐字节一致）+ 两个**消融**变体——用空串覆盖某片段即把
该块整段移除（assembler 跳过 falsy 片段），用来量化「这段文案值不值这些 token」。消融**不编造
任何新文案**，是最廉价、最诚实的第一批实验；真正要试新写法时，在此登记新 :class:`PromptProfile`
即可（key 取自 ``OVERRIDABLE_KEYS``）。

**度量边界**：登记变体是确定性的；但「哪个变体更好」需两个变体各跑真模型回合 + 裁判 / 指标对比，
属已延后的真跑评测主线。
"""

from __future__ import annotations

from agentcore.evals.types import EvalConfigError
from agentcore.runtime.prompt_profile import (
    FRAGMENT_CEO_VISUALIZATION,
    FRAGMENT_CITATION,
    PromptProfile,
)

# 名 → 变体。baseline 必为恒等（空 overrides）。消融变体用空串移除对应片段。
_REGISTRY: dict[str, PromptProfile] = {
    "baseline": PromptProfile(name="baseline", overrides={}),
    "ablate_visualization": PromptProfile(
        name="ablate_visualization", overrides={FRAGMENT_CEO_VISUALIZATION: ""}
    ),
    "ablate_citation": PromptProfile(
        name="ablate_citation", overrides={FRAGMENT_CITATION: ""}
    ),
}

PROFILE_NAMES: frozenset[str] = frozenset(_REGISTRY)


def resolve_prompt_profile(name: str | None) -> PromptProfile | None:
    """把 ``EvalCase.prompt_profile`` 名解析成变体：None / "baseline" → None（恒等）.

    返回 None 表示「无变体」，让 harness 的 ``use_profile(None)`` 走显式恒等路径（与生产
    逐字节一致）。未知名 → :class:`EvalConfigError`（配置错误，CLI 据此非 0 退出）；正常已被
    ``seed_lint`` 在加载期拦下，此处兜底。
    """
    if name is None or name == "baseline":
        return None
    try:
        return _REGISTRY[name]
    except KeyError:
        raise EvalConfigError(
            f"未知 prompt_profile: {name!r}（已注册: {sorted(PROFILE_NAMES)}）"
        ) from None
