"""续写 beat 的 run_context 必须补发 channel=task，且 body 与 feedback 逐字相等。

首轮辩手走新建 run（RunSpec.task → executor 发 task 块）；第 2+ 轮陈词 / 质询 / 结辩走
continue_run，真实指令只在 feedback 字符串里。本契约钉死：context_blocks 首块为 task，
body 直接复用同一 feedback 返回值（禁止二次改写），heading 标明环节。
"""

from agentcore.runtime.debate import (
    DebateConfig,
    DebateForm,
    DebateSide,
    JudgeVerdict,
    RoundPolicy,
    RoundResult,
    SideTurn,
    UserInterjection,
)
from agentcore.runtime.debate.prompt import (
    closing_context_blocks,
    closing_task,
    cx_answer_feedback,
    cx_context_blocks,
    round_context_blocks,
    round_feedback,
)


def _two_sides() -> list[DebateSide]:
    return [
        DebateSide(key="pro", name="正方", stance="支持做 X"),
        DebateSide(key="con", name="反方", stance="反对做 X"),
    ]


def _config() -> DebateConfig:
    return DebateConfig(
        motion="该不该做 X",
        form=DebateForm.DEBATE,
        sides=_two_sides(),
        policy=RoundPolicy(thorough=True, max_rounds=5),
    )


def _last_round() -> RoundResult:
    return RoundResult(
        round_no=1,
        focus="成本是否可控",
        turns=[
            SideTurn("pro", "正方", "r_pro", "正方上轮论点。"),
            SideTurn("con", "反方", "r_con", "反方上轮论点。"),
        ],
        verdict=JudgeVerdict(real_clash=True, new_arguments=True, converged=False),
        summary="上一轮小结。",
    )


def _task_block(blocks):  # noqa: ANN001
    tasks = [b for b in blocks if b.channel == "task"]
    assert len(tasks) == 1, f"expected exactly one task block, got {[b.channel for b in blocks]}"
    return tasks[0]


def test_round_context_task_body_equals_feedback_verbatim():
    """第 2+ 轮陈词：task.body 与 round_feedback 返回值逐字相等，heading 为「第 N 轮任务」。"""
    config, side = _config(), _two_sides()[0]
    last = _last_round()
    asks = (UserInterjection(ask="谁来兜底？", target_key="pro"),)
    feedback = round_feedback(config, side, 2, "风险", last, asks)
    blocks = round_context_blocks(config, side, 2, "风险", last, feedback, asks)
    task = _task_block(blocks)
    assert task.heading == "第 2 轮任务"
    assert task.body == feedback
    # 浓缩材料块仍在（焦点 / 追问 / 对方 / …）
    assert any(b.channel == "round_focus" for b in blocks)
    assert any(b.channel == "interjection" for b in blocks)
    assert any(b.channel == "opponent" for b in blocks)


def test_cx_context_task_body_equals_feedback_verbatim():
    """质询环节：task.body 与 cx_answer_feedback 返回值逐字相等，heading 为「质询环节」。"""
    config, side = _config(), _two_sides()[0]
    qs = ["收益口径是否含尾部？", "熔断谁买单？"]
    feedback = cx_answer_feedback(config, side, 1, "成本", qs)
    blocks = cx_context_blocks(1, qs, feedback)
    task = _task_block(blocks)
    assert task.heading == "质询环节"
    assert task.body == feedback
    assert any(b.channel == "cross_exam" for b in blocks)
    cx = next(b for b in blocks if b.channel == "cross_exam")
    assert "- 收益口径是否含尾部？" in cx.body


def test_closing_context_task_body_equals_feedback_verbatim():
    """结辩环节：task.body 与 closing_task 返回值逐字相等；closing 通道块降级为纯环节标记。"""
    config, side = _config(), _two_sides()[0]
    feedback = closing_task(config, side)
    blocks = closing_context_blocks(config, side, feedback)
    task = _task_block(blocks)
    assert task.heading == "结辩环节"
    assert task.body == feedback
    closing = next(b for b in blocks if b.channel == "closing")
    assert closing.heading == "结辩环节"
    # 退役浓缩指令：不再复述胜负手 / 禁新论据（那些只在 task/feedback 里）
    assert "胜负手" not in closing.body
    assert "新论据" not in closing.body
    assert "结辩" in closing.body
