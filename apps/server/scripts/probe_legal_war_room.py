"""探针：法律垂直 v0「答辩状作战室」端到端真跑（M2 验证）。

打开 ``legal_vertical_enabled``（上架总闸）并强制 eval 用户「已绑定」法律包，喂一份
【虚构起诉状】+「我是被告代理人，请起草答辩状」，跑【真实 team 管线】
(``run_chat_pipeline`` 经 ``EvalHarness`` team 路径)，观测 CEO 是否据
``legal_answer_brief`` Skill 端到端编排作战室：

    consult_skill(legal_answer_brief) → delegate(起草) → debate(form=red_team, is_subject)
    原告红队单向攻 → delegate(核验/格式) → 收口

打印工具调用链、委派 roster、终稿与成本，供人判断 hero 是否真的跑起来。

从 apps/server 跑（默认只跑完整 intake 单场景，省 token；thin / both 可选）::

    uv run python scripts/probe_legal_war_room.py            # = full（单场景，默认）
    uv run python scripts/probe_legal_war_room.py both       # 薄 / 完整 A/B 对比

凭据：走 ``EvalHarness`` 的 eval 凭据——优先 ``EVAL_DEEPSEEK_API_KEY``，否则回落 settings 全局
``platform_api_key``（apps/server/.env 填 ``PLATFORM_API_KEY``）。BYOK 内测下平台 key 多为空，
真跑前须在 .env 填 ``PLATFORM_API_KEY``（或导出 ``EVAL_DEEPSEEK_API_KEY``）。无 key 时本脚本
只做检测、不空调
LLM，并打印启用指引。仅 dev 探针，无任何旁路。
"""

from __future__ import annotations

import asyncio
import os
import sys

from agentcore.config import settings
from agentcore.evals.harness import EvalHarness
from agentcore.evals.types import EvalCase

# 虚构示例：买卖合同货款纠纷（常见、要素清晰、给红队留足攻击面：质量异议 / 部分已付 / 时效 / 管辖）。
_FICTIONAL_COMPLAINT = """\
民事起诉状

原告：上海晨曦贸易有限公司，住所地上海市浦东新区张江路 100 号，法定代表人 王晨，职务总经理。
被告：杭州恒达机械制造有限公司，住所地杭州市余杭区文一西路 888 号，法定代表人 李恒，职务董事长。

诉讼请求：
1. 判令被告支付拖欠货款人民币 86 万元；
2. 判令被告支付逾期付款违约金（以 86 万元为基数，按年利率 24% 自 2024 年 3 月 1 日起算至实际清偿之日止）；
3. 本案诉讼费用由被告承担。

事实与理由：
2023 年 9 月，原被告签订《工业零部件采购合同》，约定原告向被告供应数控机床配件一批，总价款 120 万元，
被告应在每批货物到货验收后 30 日内付款。原告已于 2023 年 10 月至 12 月分三批全部交付，被告仅支付 34 万元，
尚欠 86 万元经多次催讨拒不支付。被告的行为已构成根本违约，严重损害原告合法权益。为维护原告权益，特依据
《中华人民共和国民法典》相关规定，向贵院提起诉讼，请依法判如所请。

此致
杭州市余杭区人民法院

具状人：上海晨曦贸易有限公司
2025 年 6 月 1 日
"""

_USER_MESSAGE = (
    "我是被告【杭州恒达机械制造有限公司】的代理律师，刚收到原告的起诉状（见下）。"
    "请帮我起草一份民事答辩状：先把我方可能的抗辩都立起来，再让一队 AI 站在原告立场把我方答辩"
    "狠狠挑一遍漏洞、我方据此加固，引用的法条要核验，最后给我一份可复核的终稿。\n\n"
    f"——以下为原告起诉状全文——\n{_FICTIONAL_COMPLAINT}"
)

# 完整 intake 变体（M2 根因隔离）：补一份【被告方事实版本】满足 legal_answer_brief 的输入契约
# 「起诉状 + 我方事实」。薄 intake（仅起诉状）下 CEO 正确地反问要事实、hero 不点火；这份验证
# 「补齐我方事实后作战室是否随即 delegate 起草 + debate(red_team) 原告红队」。唯一变量=是否给事实。
_DEFENDANT_FACTS = """\
——以下为被告（杭州恒达机械制造有限公司）方提供的事实——
1. 货物分三批到货属实，但【第三批】数控机床配件经验收存在质量问题：精度不达标、与合同约定技术参数不符。
2. 已付 34 万元为前两批合格货物货款；第三批对应货款因质量问题依约行使后履行抗辩权暂未支付。
3. 我方已在合同约定验收期（到货后 30 日内）以书面《质量异议函》向原告提出异议，原告至今未复检或处理。
4. 合同约定逾期违约金按年利率 24% 计——我方认为过分高于实际损失（远超同期 LPR 合理倍数），请求依民法典第 585 条调减。
5. 我方持有：购销合同原件、三批到货验收记录、第三批《质量异议函》及邮寄回执、前两批付款凭证。
6. 原告起诉前未就第三批质量问题与我方协商即径行起诉。
"""

_USER_MESSAGE_FULL = (
    "我是被告【杭州恒达机械制造有限公司】的代理律师，刚收到原告起诉状（见下），并附上我方掌握的事实。"
    "请帮我起草一份民事答辩状：先把我方可能的抗辩都立起来，再让一队 AI 站在原告立场把我方答辩"
    "狠狠挑一遍漏洞、我方据此加固，引用的法条要核验，最后给我一份可复核的终稿。\n\n"
    f"——以下为原告起诉状全文——\n{_FICTIONAL_COMPLAINT}\n{_DEFENDANT_FACTS}"
)

# 关心的几类工具调用（命中即作战室真的转起来了）。
_WATCH = ("consult_skill", "delegate", "debate")


def _has_credentials() -> bool:
    if os.environ.get("EVAL_DEEPSEEK_API_KEY", "").strip():
        return True
    return bool((settings.platform_api_key or "").strip())


def _print_no_credentials() -> None:
    print("=" * 92)
    print("✗ 没有可用的 LLM 凭据，无法真跑。M2 端到端验证需要一把可用 key。")
    print("  二选一启用后重跑本脚本：")
    print("   A) 在 apps/server/.env 填  PLATFORM_API_KEY=<你的key>")
    print("   B) 导出环境变量        EVAL_DEEPSEEK_API_KEY=<你的key>（建议低额度账号）")
    print("  （脚本已就绪：上架闸会打开并强制绑定法律包、起诉状已内置，添 key 即可一键真跑。）")
    print("=" * 92)


def _hero_fired(outcome) -> bool:
    """作战室点火 = 既 delegate 组队、又跑了 debate(red_team) 原告红队。"""
    called = {name for name, _ in outcome.tool_calls}
    red_team = any(
        name == "debate" and "red_team" in args for name, args in outcome.tool_calls
    )
    return "delegate" in called and red_team


def _check_acceptance(outcome) -> None:
    """对照 §六.3 M2 验收判据核终稿：■ 脚本自动判，□ 需人眼看终稿/攻防。"""
    content = outcome.content or ""
    consulted_legal = any(
        name == "consult_skill" and "legal_answer_brief" in args
        for name, args in outcome.tool_calls
    )
    has_disclaimer = "复核" in content and ("法律意见" in content or "AI" in content)
    has_jurisdiction = "民法典" in content or "中华人民共和国" in content
    has_pending = "待核验" in content
    print("-" * 92)
    print("M2 验收判据核对（§六.3；■=脚本自动判，□=需人眼看终稿/攻防记录）:")
    print(f"  ■ ① hero 端到端点火（consult_skill+delegate+red_team） : {consulted_legal and _hero_fired(outcome)}")
    print(f"  ■ ② 终稿含免责声明（须律师复核 / 非法律意见）          : {has_disclaimer}")
    print(f"  ■ ② 终稿含法域 / 法条标注（民法典 等）                 : {has_jurisdiction}")
    print(f"  ■ ③ 终稿出现『[待核验]』兜底标记                       : {has_pending}")
    print("  □ ② 逐项对应原告 3 项诉请（货款 / 违约金 / 诉费）、无漏项 : 看下方终稿")
    print("  □ ② 红队 ≥3 攻击点被回应 / 修补                        : 看下方终稿 + debate 攻防")
    print("  □ ④ 核验 churn 受控（单 worker 不再 40+ 搜）           : 看运行日志 engine.convergence_finalize")


async def _run_and_report(label: str, case_id: str, user_message: str):
    """跑一个 intake 场景、打印读出 + 作战室命中判定，返回 outcome 供对比。"""
    case = EvalCase(
        id=case_id,
        category="team",
        user_message=user_message,
        path="team",
        mode="economy",
    )
    print("=" * 92)
    print(f"【场景】{label}")
    print("跑「答辩状作战室」端到端（真实 team 管线，可能数分钟 + 真实 token）…")
    print("-" * 92)
    outcome = await EvalHarness().run_case(case)

    print(f"finish_reason : {outcome.finish_reason}")
    print(f"rounds        : {outcome.rounds}")
    print(f"delegated     : {outcome.delegated}")
    print(f"roster        : {outcome.roster}")
    print(f"cost_usd      : {outcome.cost_usd:.4f}")
    if outcome.error:
        print(f"error         : {outcome.error}")

    print("-" * 92)
    print("工具调用链（关注 consult_skill / delegate / debate）:")
    for name, args in outcome.tool_calls:
        mark = "  ★" if name in _WATCH else "   "
        snippet = args.replace("\n", " ")[:140]
        print(f"{mark} {name}  {snippet}")

    called = {name for name, _ in outcome.tool_calls}
    consulted_legal = any(
        name == "consult_skill" and "legal_answer_brief" in args
        for name, args in outcome.tool_calls
    )
    used_red_team = any(
        name == "debate" and "red_team" in args for name, args in outcome.tool_calls
    )
    print("-" * 92)
    print("作战室命中判定:")
    print(f"  consult legal_answer_brief : {consulted_legal}")
    print(f"  delegate 组队              : {'delegate' in called}")
    print(f"  debate 原告红队(red_team)  : {used_red_team}")

    print("-" * 92)
    print("终稿（答辩状）:")
    print(outcome.content or "(空)")
    print("=" * 92)
    return outcome


async def main_async(scenario: str = "full") -> None:
    # 部署总闸直通：闸开即全员注册法律技能，无需用户绑定 / mock。
    settings.legal_vertical_enabled = True
    print("legal_vertical_enabled =", settings.legal_vertical_enabled)
    print("scenario =", scenario)

    if not _has_credentials():
        _print_no_credentials()
        return

    thin = full = None
    if scenario in ("thin", "both"):
        thin = await _run_and_report(
            "薄 intake（仅原告起诉状）— 回归用例：CEO 应正确反问要事实",
            "legal_answer_brief_thin_intake",
            _USER_MESSAGE,
        )
    if scenario in ("full", "both"):
        full = await _run_and_report(
            "完整 intake（起诉状 + 我方事实）— hero 点火 + 终稿质量验证",
            "legal_answer_brief_full_intake",
            _USER_MESSAGE_FULL,
        )
    _check_acceptance(full)

    if scenario == "both" and thin is not None and full is not None:
        print("\n" + "#" * 92)
        print("对比结论（M2 根因隔离：唯一变量 = 是否提供我方事实，mode 同为 economy）:")
        print(f"  薄 intake   hero 点火（delegate+red_team）: {_hero_fired(thin)}")
        print(f"  完整 intake hero 点火（delegate+red_team）: {_hero_fired(full)}")
        print("  → 若仅完整 intake 点火，则『缺我方事实』为主因坐实。")
        print("#" * 92)


if __name__ == "__main__":
    _scenario = sys.argv[1].strip().lower() if len(sys.argv) > 1 else "full"
    if _scenario not in ("full", "thin", "both"):
        print(f"未知场景 {_scenario!r}，可选 full | thin | both（默认 full）")
        raise SystemExit(2)
    asyncio.run(main_async(_scenario))
