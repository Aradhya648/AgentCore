"""辩论域共享常量（prompt / schema / events 共用，单一源）。"""

from __future__ import annotations

from agentcore.runtime.debate.types import DebateForm

DEBATE_OUTPUT_LIMIT = 16000

# 辩手最小权限工具集（least-privilege）：取证类（查资料 / 读网页）+ 只读文件三件套
# （消费幕1 research/ 案卷），不给写文件 / 代码 / 委派 / 提问等副作用工具——辩手职责是论证
# 而非动手改东西。首轮经 task 的 tools 字段成为 allow-list，后续轮经 session.spec 自动沿用。
DEBATER_TOOLS = ("web_search", "read_url", "file_read", "file_list", "grep")

# 证人只读工具集（批 D1）：与辩手取证同形，禁写盘 / handoff / 委派。
WITNESS_TOOLS = ("web_search", "read_url", "file_read", "file_list", "grep")

# 庭前取证员（§二之二）：与证人同形只读叶子；无发言、无 delegate。
INVESTIGATOR_TOOLS = WITNESS_TOOLS
# thorough 每方取证员上限（预算对称夹紧）。
MAX_INVESTIGATORS_PER_SIDE = 2
# 主辩点单每方任务硬顶。
MAX_EVIDENCE_ORDER_TASKS = 3
# 取证员 per-run 检索预算（各方同额；待实测校准）。
DEFAULT_INVESTIGATOR_RETRIEVAL_BUDGET = 6

# 辩手发言长度指引：旧观测里单方动辄数千 token（一条就几十秒），既拖慢又稀释论点。引导「宁深
# 勿长」——聚焦最有力的少数论点，显著降低每轮墙钟与 token。首轮立论与后续轮续写都注入。
LENGTH_HINT = (
    "聚焦你最有力的 2–3 个论点、约 400–600 字讲透，宁深勿长——不堆砌、不面面俱到。"
)

# 结辩陈词长度预算（阶段化发言角色 P4）：结辩是收束不是新立论，比逐轮发言更短——只留最能定胜负的
# 话。显著收紧长度是「阶段化长度预算」的落点（立论 400–600 字 → 结辩 150–250 字），避免结辩变成
# 又一轮长篇复述。仅结辩环节（:func:`~agentcore.runtime.debate.prompt.closing_task`）注入。
CLOSING_LENGTH_HINT = (
    "结辩要【短而有力】：约 150–250 字收束，只留最能定胜负的话，删掉一切铺垫、复述与新枝节。"
)

# 质询作答长度预算：逐条须写完（表态 + 论据），禁止在冒号 / 列举 /「理由是」处截断。
# 仅质询成稿 brief（:func:`~agentcore.runtime.debate.prompt.cx_draft_brief`）注入；
# 装配端另有尾部悬垂检测 + 一次自动续写补全。
CX_LENGTH_HINT = (
    "质询作答须【逐条写完】：每条约 120–220 字讲透表态与论据；每条必须以完整句子收束，"
    "禁止在冒号、未闭合列表或「理由是 / 如下 / 包括」处截断停笔。"
)

# 「快速对碰」(thorough=False，主持人单轮即收) 的辩手附加约束。观测：即便是 trivial 命题，快速辩
# 论的辩手仍各刷十余次 web_search、跑近十轮 ReAct（自停于内容、远未触及安全上限），墙钟与成本几乎
# 全耗在这。轮数上限不是有效杠杆（辩手自停在上限内），真正的杠杆是【告诉辩手这是轻量交锋】——直接
# 压「检索次数」与「论点广度」。仅快速模式注入；认真辩透（thorough=True）不加，保留深挖取证。
QUICK_DEBATER_HINT = (
    "【快速对碰】这是一次轻量单轮交锋：以你的常识与推理直接立论，能不检索就不检索"
    "（至多 1 次必要取证），只把你【最有力的 1 个论点】讲透即可——不深挖、不多角度铺开。"
)

FORM_LABELS = {
    DebateForm.DEBATE: "正反辩论",
    DebateForm.RED_TEAM: "红队挑刺",
    DebateForm.ROUNDTABLE: "多方圆桌",
}
