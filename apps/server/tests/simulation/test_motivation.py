"""WS-D: motivation/utility layer — non-neutral, explainable, persona-driven scores."""

from __future__ import annotations

from agentcore.simulation.agents.models import MotivationAssessment, MotivationSignals
from agentcore.simulation.scenarios.town.config import (
    CHEN_PERSONA,
    LIN_PERSONA,
    SUN_PERSONA,
    ZHANG_PERSONA,
)


def test_scores_are_non_neutral_and_bounded():
    assessment = MotivationAssessment.evaluate(LIN_PERSONA, MotivationSignals(money=15))
    for value in (assessment.urgency, assessment.social_pull, assessment.resource_need):
        assert 0.0 <= value <= 1.0
    # Explicitly not the flat 0.5/0.5/0.5 placeholder.
    rounded = {
        round(assessment.urgency, 3),
        round(assessment.social_pull, 3),
        round(assessment.resource_need, 3),
    }
    assert rounded != {0.5}
    assert assessment.rationale


def test_low_money_and_money_goal_drive_resource_need():
    broke = MotivationAssessment.evaluate(LIN_PERSONA, MotivationSignals(money=10))
    flush = MotivationAssessment.evaluate(LIN_PERSONA, MotivationSignals(money=200))
    assert broke.resource_need > flush.resource_need
    assert broke.dominant_drive == "谋生赚钱"
    assert any("生计" in r or "经济压力" in r for r in broke.rationale)


def test_extraversion_shapes_social_pull():
    context = MotivationSignals(others_present=3)
    extravert = MotivationAssessment.evaluate(SUN_PERSONA, context)
    introvert = MotivationAssessment.evaluate(ZHANG_PERSONA, context)
    assert extravert.social_pull > introvert.social_pull


def test_storm_raises_urgency_with_reason():
    calm = MotivationAssessment.evaluate(CHEN_PERSONA, MotivationSignals())
    storm = MotivationAssessment.evaluate(CHEN_PERSONA, MotivationSignals(storm_active=True))
    assert storm.urgency > calm.urgency
    assert any("暴风雨" in r for r in storm.rationale)


def test_market_prices_add_resource_pressure():
    normal = MotivationAssessment.evaluate(LIN_PERSONA, MotivationSignals())
    pricey = MotivationAssessment.evaluate(
        LIN_PERSONA, MotivationSignals(market_price_multiplier=1.8)
    )
    assert pricey.resource_need >= normal.resource_need
    assert any("物价" in r for r in pricey.rationale)


def test_hint_line_mentions_dominant_drive():
    assessment = MotivationAssessment.evaluate(LIN_PERSONA, MotivationSignals(money=10))
    line = assessment.hint_line()
    assert "内在驱动" in line
    assert assessment.dominant_drive in line
