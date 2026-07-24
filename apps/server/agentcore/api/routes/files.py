"""文件编辑辅助路由（AI 改写）。

这里是**无状态**的文本助手：服务端从不读写文件本身（本地文件在桌面 fs 桥后、云端文件
在工作区 API 后），编辑器把「选区 + 指令 + 前后文」作为文本发来，拿回改写版后由前端逐块
评审落地。无持久化、无文件路径——纯文本进、文本出，按 ``scenario="file.rewrite"`` 归因花费。

路由是薄层：计费/凭据 preflight + provider 构建 + 改写都在 ``assist.rewrite`` 服务里
（api ⊥ llm），这里只做依赖装配与请求/响应映射。
"""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from agentcore.api.dependencies import AuthUser, get_cost_event_repo, get_db
from agentcore.api.schemas import RewriteRequest, RewriteResponse
from agentcore.assist.rewrite import RewriteInput, rewrite_selection_for_user
from agentcore.db.repositories import CostEventRepository

router = APIRouter(prefix="/files", tags=["files"])


@router.post("/assist/rewrite", response_model=RewriteResponse)
async def rewrite_file_selection(
    body: RewriteRequest,
    user: AuthUser,
    session: AsyncSession = Depends(get_db),
    cost_repo: CostEventRepository = Depends(get_cost_event_repo),
) -> RewriteResponse:
    """按自由指令改写文档中的一段选区。

    无状态、无路径：入参携带选区与前后文文本，返回改写后的选区，交前端用 merge view
    逐块评审。全程不落库。
    """
    rewritten = await rewrite_selection_for_user(
        session=session,
        user=user,
        cost_repo=cost_repo,
        data=RewriteInput(
            selection=body.selection,
            instruction=body.instruction,
            context_before=body.context_before,
            context_after=body.context_after,
        ),
    )
    return RewriteResponse(rewritten=rewritten)
