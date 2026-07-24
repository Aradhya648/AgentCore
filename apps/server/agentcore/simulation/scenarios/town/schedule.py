"""AI Town daily schedule (leaf module, import-order-independent).

Split out of ``config.py`` so the schedule lookups the agents package needs
(``tick_runner`` / ``activation`` / ``memory``) no longer force a load of
``config`` — which in turn pulls in ``agents.models`` and closes a circular
import. This module depends only on stdlib + pydantic; ``SimPersona`` is a
``TYPE_CHECKING``-only reference (``persona.role`` is plain attribute access at
runtime), keeping it a true leaf.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from pydantic import BaseModel

if TYPE_CHECKING:
    from agentcore.simulation.agents.models import SimPersona


class ScheduleSlot(BaseModel):
    """Default location + activity for one hour of the town day."""

    location: str
    activity: str


def _slot(location: str, activity: str) -> ScheduleSlot:
    return ScheduleSlot(location=location, activity=activity)


# Baseline town rhythm; residents may deviate via LLM decisions.
# Peaks for new districts: 13 图书馆, 14 工坊, 17 码头 (multi-resident via overrides).
HOURLY_SCHEDULE: tuple[ScheduleSlot, ...] = (
    _slot("住宅区", "睡觉"),
    _slot("住宅区", "睡觉"),
    _slot("住宅区", "睡觉"),
    _slot("住宅区", "睡觉"),
    _slot("住宅区", "睡觉"),
    _slot("住宅区", "起床洗漱"),
    _slot("住宅区", "做早饭"),
    _slot("面包店", "开门准备"),
    _slot("市场", "早市开张"),
    _slot("广场", "晨练聚集"),
    _slot("市场", "买卖高峰"),
    _slot("餐厅", "午餐营业"),
    _slot("公园", "午休散步"),
    _slot("图书馆", "午后阅览"),
    _slot("工坊", "手作忙碌"),
    _slot("广场", "闲聊社交"),
    _slot("镇政厅", "公务办理"),
    _slot("码头", "傍晚散步"),
    _slot("餐厅", "晚餐高峰"),
    _slot("住宅区", "回家休息"),
    _slot("公园", "晚间散步"),
    _slot("住宅区", "居家放松"),
    _slot("住宅区", "洗漱就寝"),
    _slot("住宅区", "入睡"),
)

# Role-specific overrides keyed by hour; falls back to HOURLY_SCHEDULE.
# Intentionally route extra residents into 图书馆 / 工坊 / 码头 at peak hours
# so those zones feel populated (not only 张静 / 吴师傅 alone).
ROLE_HOURLY_OVERRIDES: dict[str, dict[int, ScheduleSlot]] = {
    "面包师": {
        7: _slot("面包店", "和面开炉"),
        8: _slot("面包店", "出炉摆柜"),
        14: _slot("工坊", "取定制托盘"),
    },
    "退休教师": {
        9: _slot("公园", "下棋"),
        11: _slot("图书馆", "读报借书"),
        13: _slot("图书馆", "午后读书会"),
        15: _slot("公园", "晒太阳聊天"),
        17: _slot("码头", "傍晚散步"),
    },
    "杂货店老板": {
        10: _slot("市场", "守店揽客"),
        14: _slot("工坊", "订做货箱"),
        16: _slot("市场", "盘点库存"),
    },
    "菜贩": {
        8: _slot("市场", "摆摊卖菜"),
        14: _slot("工坊", "看木器摊"),
        17: _slot("码头", "收摊后散步"),
    },
    "镇派出所民警": {
        9: _slot("广场", "巡逻"),
        13: _slot("码头", "巡查岸边"),
        16: _slot("市场", "维持秩序"),
        17: _slot("码头", "傍晚巡岸"),
    },
    "餐馆老板": {
        11: _slot("餐厅", "后厨忙"),
        13: _slot("图书馆", "查菜谱灵感"),
        17: _slot("码头", "看海鲜到货"),
        18: _slot("餐厅", "招待客人"),
    },
    "图书管理员": {
        10: _slot("图书馆", "整理借阅"),
        13: _slot("图书馆", "主持阅览"),
        14: _slot("图书馆", "读者服务"),
    },
    "社区护士": {
        9: _slot("住宅区", "上门随访"),
        13: _slot("图书馆", "健康讲座资料"),
        15: _slot("广场", "健康咨询"),
        17: _slot("码头", "晚间散步"),
    },
    "手工艺人": {
        9: _slot("工坊", "开炉备料"),
        10: _slot("工坊", "打磨木器"),
        13: _slot("工坊", "接待访客"),
        14: _slot("工坊", "手作高峰"),
        16: _slot("工坊", "收工清扫"),
    },
    "镇长秘书": {
        9: _slot("镇政厅", "整理公文"),
        11: _slot("码头", "查看货运"),
        13: _slot("图书馆", "查档阅卷"),
        16: _slot("镇政厅", "接待来访"),
        17: _slot("码头", "傍晚巡视"),
    },
}


def schedule_for_hour(hour: int) -> ScheduleSlot:
    """Default town schedule slot for clock hour ``0–23``."""
    return HOURLY_SCHEDULE[hour % 24]


def schedule_hint_for_persona(persona: SimPersona, hour: int) -> ScheduleSlot:
    """Schedule hint for one resident; role overrides take precedence."""
    overrides = ROLE_HOURLY_OVERRIDES.get(persona.role, {})
    return overrides.get(hour % 24, schedule_for_hour(hour))
