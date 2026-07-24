"""File assist (AI 改写) schemas."""

from pydantic import BaseModel, Field


class RewriteRequest(BaseModel):
    """选区改写入参（无状态、无路径）：把选中文本按指令改写，前后文仅作语境只读。"""

    # 选中文本：必填。上限约束 LLM 成本，单段散文/小节足够；超大选区由前端切分或拒绝。
    selection: str = Field(..., min_length=1, max_length=20000)
    instruction: str = Field(..., min_length=1, max_length=2000)
    # 选区前/后的上下文，给模型衔接语气/术语用——只读，绝不参与改写输出。
    context_before: str = Field("", max_length=4000)
    context_after: str = Field("", max_length=4000)


class RewriteResponse(BaseModel):
    """改写结果：替换选区的文本，由前端套 merge view 逐块评审（人决定接受/拒绝）。"""

    rewritten: str
