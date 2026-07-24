"""SimAgent persona and motivation models (M1, content layer WS-D)."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import BaseModel, Field


class BigFive(BaseModel):
    openness: float = Field(default=0.5, ge=0.0, le=1.0)
    conscientiousness: float = Field(default=0.5, ge=0.0, le=1.0)
    extraversion: float = Field(default=0.5, ge=0.0, le=1.0)
    agreeableness: float = Field(default=0.5, ge=0.0, le=1.0)
    neuroticism: float = Field(default=0.5, ge=0.0, le=1.0)


class SimPersona(BaseModel):
    """Immutable role card for one SimAgent."""

    agent_id: str
    name: str
    role: str
    location: str
    goal: str
    system_prompt: str
    big_five: BigFive = Field(default_factory=BigFive)
    goals_stack: list[str] = Field(default_factory=list)

    def effective_goals(self) -> list[str]:
        if self.goals_stack:
            return list(self.goals_stack)
        return [self.goal] if self.goal else []


# --- Motivation / utility layer (WS-D) -----------------------------------------------
#
# Turns the flat neutral placeholder into an explainable, non-neutral drive estimate.
# Scores are pure functions of (persona traits + current world signals) so the layer is
# fully unit-testable and deterministic; ``rationale`` records why each drive fired.

# Money at/above which economic pressure is effectively gone; at/below which it maxes out.
_MONEY_COMFORT = 120.0
_MONEY_FLOOR = 20.0
# Goal keywords that mark a livelihood-driven agent (raises resource_need).
_MONEY_KEYWORDS = ("钱", "房租", "卖", "攒", "进货", "库存", "生意", "价", "币", "赚")


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


@dataclass(frozen=True)
class MotivationSignals:
    """Current-tick world signals feeding the motivation estimate (internal)."""

    hour: int = 12
    mood: float = 0.0
    money: float = 100.0
    others_present: int = 0
    at_home: bool = False
    market_price_multiplier: float = 1.0
    storm_active: bool = False
    festival_active: bool = False


class MotivationAssessment(BaseModel):
    """Explainable per-tick drive estimate that nudges (not dictates) the LLM decision."""

    urgency: float = Field(default=0.5, ge=0.0, le=1.0)
    social_pull: float = Field(default=0.5, ge=0.0, le=1.0)
    resource_need: float = Field(default=0.5, ge=0.0, le=1.0)
    rationale: list[str] = Field(default_factory=list)

    @property
    def dominant_drive(self) -> str:
        scores = {
            "谋生赚钱": self.resource_need,
            "寻求社交": self.social_pull,
            "应对当务之急": self.urgency,
        }
        return max(scores, key=lambda key: scores[key])

    def hint_line(self) -> str:
        """One-line perception injection summarising the dominant drive + top reasons."""
        drivers = "、".join(self.rationale[:2]) if self.rationale else "各项驱动力平稳"
        return (
            f"【内在驱动】此刻主导你的是「{self.dominant_drive}」"
            f"（紧迫{self.urgency:.0%}/社交{self.social_pull:.0%}/生计{self.resource_need:.0%}）。"
            f"{drivers}。请让本 tick 的行动体现这股劲头，而非机械照日程。"
        )

    @staticmethod
    def evaluate(persona: SimPersona, signals: MotivationSignals) -> MotivationAssessment:
        big_five = persona.big_five
        rationale: list[str] = []

        resource_need = _resource_need(persona, signals, big_five, rationale)
        social_pull = _social_pull(signals, big_five, rationale)
        urgency = _urgency(signals, big_five, resource_need, rationale)

        if not rationale:
            rationale.append("各项驱动力平稳，无突出压力")
        return MotivationAssessment(
            urgency=urgency,
            social_pull=social_pull,
            resource_need=resource_need,
            rationale=rationale,
        )


def _resource_need(
    persona: SimPersona,
    signals: MotivationSignals,
    big_five: BigFive,
    rationale: list[str],
) -> float:
    if signals.money <= _MONEY_FLOOR:
        money_pressure = 1.0
    elif signals.money >= _MONEY_COMFORT:
        money_pressure = 0.0
    else:
        money_pressure = (_MONEY_COMFORT - signals.money) / (_MONEY_COMFORT - _MONEY_FLOOR)

    goal_text = " ".join(persona.effective_goals())
    goal_is_money = any(keyword in goal_text for keyword in _MONEY_KEYWORDS)

    # Conscientious residents fret more about ledgers and supplies.
    score = 0.15 + 0.6 * money_pressure + 0.1 * (big_five.conscientiousness - 0.5)
    if goal_is_money:
        score += 0.2
        rationale.append("当前目标与生计/买卖直接相关")
    if money_pressure > 0.5:
        rationale.append(f"手头仅约{signals.money:.0f}币，经济压力偏高")
    if signals.market_price_multiplier > 1.01:
        score += 0.1 * min(1.0, signals.market_price_multiplier - 1.0)
        rationale.append(f"市场物价约平时{signals.market_price_multiplier:.1f}倍，进货吃紧")
    return _clamp01(score)


def _social_pull(
    signals: MotivationSignals,
    big_five: BigFive,
    rationale: list[str],
) -> float:
    # Extraversion is the backbone; agreeableness adds warmth.
    score = 0.1 + 0.5 * big_five.extraversion + 0.2 * big_five.agreeableness
    if signals.others_present > 0:
        score += min(0.25, 0.08 * signals.others_present)
        rationale.append(f"身边有{signals.others_present}人，社交机会现成")
    if signals.festival_active:
        score += 0.2
        rationale.append("广场庆典气氛热烈，想凑热闹")
    if signals.mood < -0.3 and big_five.extraversion < 0.5:
        score -= 0.15
        rationale.append("心情低落且性子偏内向，倾向独处")
    return _clamp01(score)


def _urgency(
    signals: MotivationSignals,
    big_five: BigFive,
    resource_need: float,
    rationale: list[str],
) -> float:
    # Neuroticism is the anxiety baseline; acute stressors stack on top.
    score = 0.15 + 0.4 * big_five.neuroticism + 0.2 * resource_need
    if signals.storm_active:
        score += 0.35
        rationale.append("暴风雨来袭，需尽快决定去留")
    if signals.mood < -0.3:
        score += 0.2 * min(1.0, -signals.mood)
        rationale.append("情绪不佳，急于改变现状")
    if signals.hour >= 21 or signals.hour <= 5:
        score += 0.15
        rationale.append("已是深夜，作息驱使尽快归家")
    return _clamp01(score)
