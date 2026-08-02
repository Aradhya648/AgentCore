"""Tests for system Skills + consult_skill (提示词瘦身 P2 — 渐进披露).

Covers the three moving parts of the prompt-slimming slice:

1. ``SkillRegistry`` / ``build_system_skill_registry`` — name lookup (hit/miss) and
   the ``requires_tools`` visibility filter.
2. ``render_skill_directory`` — the always-on 能力目录 lists only skills whose required
   tools are wired this turn (so it never advertises a capability the CEO lacks).
3. ``ConsultSkillTool`` — returns a skill's full body (CONTINUE) on a hit, and
   degrades gracefully (non-fatal, lists names) on an unknown name.

Plus a guard that each skill BODY still teaches the mechanism it owns — the
assertions that used to pin these in the always-on CEO hint, now relocated to the
skills they were externalised into.
"""

from pathlib import Path

from agentcore.core.types import ToolCategory
from agentcore.runtime.skills import (
    SkillRegistry,
    SystemSkill,
    build_system_skill_registry,
    render_skill_directory,
)
from agentcore.tools.builtin.consult_skill import ConsultSkillTool
from agentcore.tools.protocol import ToolContext
from agentcore.tools.sandbox.subprocess import SubprocessSandbox
from agentcore.workspace.server import ServerWorkspace

# debate / delegate are wired on every path; ask_user is live-user only.
# verify_and_fix / long_form_writing / team_orchestration_advanced ride delegate.
_FULL_TOOLS = {"delegate", "ask_user", "debate"}
_NO_LIVE_USER = {"delegate", "debate"}  # autonomous path: no ask_user


def _ctx() -> ToolContext:
    # consult_skill never touches the backend; a real one only satisfies the shape.
    return ToolContext(
        execution_id="e",
        run_id="s",
        agent_id="a",
        backend=ServerWorkspace(root=Path("."), sandbox=SubprocessSandbox()),
        user_id="u",
    )


# --- registry ----------------------------------------------------------------


def test_registry_registers_the_system_skills():
    reg = build_system_skill_registry()
    names = {s.name for s in reg.list_all()}
    assert names == {
        "team_orchestration_advanced",
        "work_discipline",
        "build_website",
        "build_toolshed",
        "build_app",
        "debate_and_review",
        "revising_a_product",
        "ask_user_kickoff",
        "ask_user_midtask",
        "delegate_checkpoint",
        "verify_and_fix",
        "long_form_writing",
        "deep_multi_lens_research",
    }


def test_registry_get_hit_and_miss():
    reg = build_system_skill_registry()
    assert reg.get("debate_and_review") is not None
    assert reg.get("no_such_skill") is None


def test_registry_rejects_duplicate_name():
    reg = SkillRegistry()
    reg.register(SystemSkill(name="x", summary="s", body="b"))
    try:
        reg.register(SystemSkill(name="x", summary="s2", body="b2"))
    except ValueError:
        pass
    else:  # pragma: no cover - the register must raise
        raise AssertionError("duplicate skill name should raise ValueError")


def test_available_hides_gated_skills_without_required_tools():
    # The ask_user_* skills (and delegate_checkpoint, which pauses for user review)
    # need the ask_user tool. On the autonomous (no live user) path it is not wired,
    # so those skills drop out of the catalog. verify_and_fix rides delegate (the
    # delegated dev loop), so it stays available on the autonomous path.
    reg = build_system_skill_registry()
    available = {s.name for s in reg.available(_NO_LIVE_USER)}
    assert "team_orchestration_advanced" in available
    assert "build_website" in available
    assert "debate_and_review" in available
    assert "revising_a_product" in available
    assert "verify_and_fix" in available
    assert "work_discipline" in available
    assert "ask_user_kickoff" not in available
    assert "ask_user_midtask" not in available
    assert "delegate_checkpoint" not in available


def test_available_shows_gated_skills_when_tools_wired():
    reg = build_system_skill_registry()
    available = {s.name for s in reg.available(_FULL_TOOLS)}
    assert "ask_user_kickoff" in available
    assert "ask_user_midtask" in available
    assert "delegate_checkpoint" in available
    assert "verify_and_fix" in available


# --- directory rendering -----------------------------------------------------


def test_directory_lists_only_available_skills_with_names_and_summaries():
    reg = build_system_skill_registry()
    out = render_skill_directory(reg, _FULL_TOOLS)
    assert "<能力目录>" in out and "</能力目录>" in out
    assert "consult_skill" in out  # the soft push to pull a skill
    for skill in reg.list_all():
        assert skill.name in out
        assert skill.summary in out


def test_directory_omits_gated_skills_on_autonomous_path():
    reg = build_system_skill_registry()
    out = render_skill_directory(reg, _NO_LIVE_USER)
    assert "ask_user_kickoff" not in out
    assert "ask_user_midtask" not in out
    assert "delegate_checkpoint" not in out
    # The delegate-gated + non-gated advanced skills are still offered.
    assert "team_orchestration_advanced" in out
    assert "verify_and_fix" in out


def test_directory_empty_when_nothing_available():
    # A registry whose every skill is gated behind an un-wired tool renders nothing,
    # so the caller appends nothing (no empty <能力目录> block).
    reg = SkillRegistry()
    reg.register(SystemSkill(name="x", summary="s", body="b", requires_tools=("missing_tool",)))
    assert render_skill_directory(reg, set()) == ""


# --- consult_skill tool ------------------------------------------------------


def test_consult_skill_schema_is_ceo_orchestration_primitive():
    # consult_skill is a CEO orchestration primitive (not a「技能」-category tool):
    # 技能 are Prompt injection shown in the「AI 提示词」catalog, never a tool group.
    tool = ConsultSkillTool(registry=build_system_skill_registry())
    schema = tool.schema
    assert schema.name == "consult_skill"
    assert schema.category is ToolCategory.ORCHESTRATION


async def test_consult_skill_returns_body_on_hit():
    reg = build_system_skill_registry()
    tool = ConsultSkillTool(registry=reg)
    result = await tool.execute({"name": "debate_and_review"}, _ctx())
    assert result.success
    assert result.output == reg.get("debate_and_review").body


async def test_consult_skill_build_website_hit():
    """能力目录对齐：consult_skill('build_website') 可命中（回归 miss→none 旁路）。"""
    reg = build_system_skill_registry()
    assert reg.get("build_website") is not None
    tool = ConsultSkillTool(registry=reg)
    result = await tool.execute({"name": "build_website"}, _ctx())
    assert result.success
    assert "playbook=\"build_website\"" in result.output
    assert "none" in result.output
    directory = render_skill_directory(reg, _NO_LIVE_USER)
    assert "- build_website：" in directory
    assert "- build_toolshed：" in directory


async def test_consult_skill_build_toolshed_hit():
    reg = build_system_skill_registry()
    assert reg.get("build_toolshed") is not None
    tool = ConsultSkillTool(registry=reg)
    result = await tool.execute({"name": "build_toolshed"}, _ctx())
    assert result.success
    assert "playbook=\"build_toolshed\"" in result.output
    assert "tool_dense" in result.output
    assert "none" in result.output


async def test_consult_skill_degrades_on_unknown_name():
    tool = ConsultSkillTool(registry=build_system_skill_registry())
    result = await tool.execute({"name": "bogus"}, _ctx())
    assert not result.success
    # Graceful: lists the available names so the model can retry (no turn-breaking).
    assert "team_orchestration_advanced" in result.output


async def test_consult_skill_playbook_name_miss_hints_delegate():
    """Known playbook mistaken for skill → point at delegate(playbook=…); no new skill."""
    tool = ConsultSkillTool(registry=build_system_skill_registry())
    result = await tool.execute({"name": "build_feature"}, _ctx())
    assert not result.success
    assert "playbook" in result.output
    assert 'delegate(playbook="build_feature"' in result.output
    # Must not invent a build_feature skill body.
    assert result.output.count("build_feature") >= 1


async def test_consult_skill_repair_code_miss_hints_continue_from_when_investigated():
    """repair_code 误当 skill → 分流：无调查批用 playbook；已有调查批 → 手写+continue_from。"""
    tool = ConsultSkillTool(registry=build_system_skill_registry())
    result = await tool.execute({"name": "repair_code"}, _ctx())
    assert not result.success
    assert "playbook" in result.output
    assert "continue_from_run_id" in result.output
    assert "调查" in result.output
    assert "revising_a_product" in result.output


async def test_consult_skill_handles_missing_name_arg():
    tool = ConsultSkillTool(registry=build_system_skill_registry())
    result = await tool.execute({}, _ctx())
    assert not result.success


# --- skill bodies still teach their mechanisms (relocated from the CEO hint) --


def _body(name: str) -> str:
    return build_system_skill_registry().get(name).body


def test_team_orchestration_skill_teaches_shape_vocabulary():
    # 协作优先重设计阶段 2：skill 教形状词汇表 + 组合规则 + 三档，playbook 降为教学示例。
    body = _body("team_orchestration_advanced")
    for term in (
        "并列对象分组",
        "角度扇出",
        "证据驱动流水线",
        "独立审查",
        "有界返工环",
        "契约共享面",
        "独立多透镜诊断",
        "部件一致性对账",
        "对抗辩论",
        "发散挑选",
    ):
        assert term in body, term
    assert "默认中档" in body
    assert "教学示例形状" in body and "对照学形状" in body
    assert "免手搓" not in body  # 旧广告口径已撤
    assert "research_report" in body  # listing still present as teaching examples
    assert "parallel_brief" in body
    assert "结局分层" in body or "对齐推进" in body
    assert "成文交付" in body or "成文专线" in body or "成篇" in body
    assert "默认 A" in body or "少扇出" in body
    assert "材料已齐" in body
    # B 成文：落盘文档 + ≥2 角 → 各角与主笔均 files + 末环独立审校
    assert "角 prose" in body and "仅主笔落盘" in body
    assert "form=files" in body and "artifacts" in body
    assert "独立审校" in body
    assert "调研→撰稿" in body
    assert "质量缝" in body


def test_work_discipline_skill_teaches_design_and_patch_tripwires():
    body = _body("work_discipline")
    assert "设计三问" in body
    assert "补丁绊线" in body
    assert "探索信任" in body
    assert "讨论与查证分相" in body
    assert "work_authority" in body
    assert "escalate" in body
    # worker 自主度不进本 skill（已在 identity）
    assert "小问题（路径拼写" not in body


def test_team_orchestration_skill_teaches_delegate_knobs():
    # Relocated from the old always-on hint: quality contract, output shaping,
    # finalize, the DAG-vs-nesting distinction (model tiers were removed).
    body = _body("team_orchestration_advanced")
    assert "deliverable" in body
    assert "finalize" in body
    assert "coordinate" in body and "coordinate=false" in body
    assert "depends_on" in body and "同一层" in body
    # 依赖流水线 bullet 须教「派前先判生产者→消费者」+ 正反例（何时串行 / 何时并行），
    # 而非只讲 DAG 机械怎么填——修复 CEO 默认全平铺把有先后的流水线拍平的根因。
    assert "生产者→消费者" in body
    assert "正例·串行" in body and "反例·勿串" in body
    assert "嵌套委派" in body and "大模块" in body
    assert "默认" in body and "二选一" in body
    assert "禁止再平铺" in body
    # 协调补派失败节点须标 replaces_run_id，引擎改写下游 depends_on
    assert "replaces_run_id" in body and "补派" in body
    # 纠正「一次只能一个 delegate / 同步阻塞到全队完成」误述：一回合一张图 + 同回合可再追加；
    # 禁止同构重派在跑任务。
    assert "一回合一张协作图" in body
    assert "再调" in body and "delegate" in body
    assert "同构" in body
    assert "不必" in body or "不是" in body  # 否定「必须等全队完成」
    # 跨回合延续：默认新图、显式延续才 append（latest 主路径）+ 呈现一致的收尾口径。
    assert "【跨回合延续】" in body
    assert 'append_to_execution_id="latest"' in body
    assert "默认新回合新建图" in body
    assert "已往上方协作图追加" in body
    assert "在同一回合的同一张图里" in body  # 禁令口径
    # latest 未命中 → 自动降级新建（勿教硬失败再改口）
    assert "自动降级" in body or "已自动" in body
    assert "硬失败再改口" in body or "勿先硬失败" in body


def test_team_orchestration_skill_teaches_constraint_vs_solution_and_outline_step():
    # 认知分工 + 结构跟着证据走（L3/L4，法律论文案例的根因修复）: the skill teaches that
    # a deliverable's professional STRUCTURE belongs to the expert worker (not the
    # CEO's task), that contract.required_sections is an acceptance floor (not a
    # structure blueprint), and that研究级大型交付 should make「定结构」an evidence-driven,
    # user-gated outline step (调研 → 提纲 + checkpoint_after → 全文) rather than the
    # CEO fixing the skeleton up front. Pins the范式 so it can't silently drop out.
    body = _body("team_orchestration_advanced")
    assert "方案" in body  # 约束 vs 方案
    assert "required_sections" in body  # 验收底线、非结构蓝图
    assert "提纲" in body
    assert "checkpoint_after" in body
    # 定案 A：调研驱动大型交付 — 各角 MD 笔记 files，禁三人 prose 只靠主笔落盘
    assert "三人 prose" in body or "角 prose" in body
    assert "仅主笔落盘" in body or "只靠主笔落盘" in body
    # 成文 PDF：md → md_to_pdf → handoff；禁 HTML/reportlab 主路径
    assert "md_to_pdf" in body
    assert "HTML" in body and "reportlab" in body
    # 演讲/PPT：禁代写全章节大纲 / Marp 语法细则（钉在约束 vs 方案）
    assert "代写全章节大纲" in body
    assert "Marp" in body


def test_team_orchestration_skill_teaches_presentation_pptx_honesty():
    """有执行须真 pptx；无执行允许 Marp/脚本但禁假称 PPT 已落盘。"""
    body = _body("team_orchestration_advanced")
    assert "python-pptx" in body
    assert "静默" in body and ".md" in body
    assert "PPT 已落盘可直接使用" in body
    assert "交付缺口" in body or "标缺口" in body


def test_team_orchestration_skill_teaches_must_contain_and_sections_discipline():
    # 定案甲：细则进任务范围/章节/落盘路径；停止主推细清单进 must_contain；
    # 若保留须标软提醒/短主题词。禁机构名/取证路径词；required_sections 只留少数验收点。
    body = _body("team_orchestration_advanced")
    assert "must_contain" in body
    assert "软提醒" in body or "短主题词" in body
    assert "停止" in body or "勿塞细" in body or "细枚举" in body
    assert "取证路径" in body or "机构名" in body
    assert "Stanford" in body or "McKinsey" in body  # 真跑反例警示
    assert "required_sections" in body
    assert "验收点" in body or "验收项" in body
    assert "2–4" in body or "2-4" in body
    # 不再主推「细则清单进 must_contain」
    assert "细则清单进 `deliverable.must_contain`" not in body
    assert "细则清单进 deliverable.must_contain" not in body


def test_team_orchestration_skill_teaches_parallel_review_notewall():
    # 并行审查须经 post_note 广播方向级问题（便签墙），再各自挑细节。
    # 决策现状见 docs/03-AI核心/Agent协作模式.md（波内共享上下文 / 便签墙）。
    body = _body("team_orchestration_advanced")
    assert "post_note" in body and "heads_up" in body
    assert "并行审查" in body or "并行" in body


def test_team_orchestration_skill_teaches_review_contract_template():
    # 审查默认 prose + 中文 required_sections；结构化 JSON 仅走文件通道（artifacts）。
    # 钉：格式只在 deliverable、task 不双写、勿混用 json+required_sections、web_search 软引导。
    body = _body("team_orchestration_advanced")
    assert "审查类任务的统一契约" in body
    assert "默认 prose" in body
    assert 'required_sections": ["问题", "建议", "评分"]' in body
    assert "结构化交付走文件通道" in body
    assert "artifacts" in body and "output_format" in body and "json" in body
    assert "禁止" in body  # 混用防御
    assert "web_search" in body
    assert "全文" in body or "复制" in body
    assert "deliverable" in body
    assert "custom" in body and "不被引擎验证" in body
    assert "problems" in body and "suggestions" in body and "score" in body


def test_team_orchestration_skill_teaches_seed_notes_and_team_brief():
    body = _body("team_orchestration_advanced")
    assert "seed_notes" in body and "team_brief" in body
    assert 'coordination="wall"' in body or "coordination" in body
    assert "wall" in body and "none" in body
    assert "正交" in body or "互不依赖" in body


def test_team_orchestration_skill_teaches_coordination_wall_vs_none():
    body = _body("team_orchestration_advanced")
    assert "coordination" in body
    assert "wall" in body and "none" in body
    assert "build_feature" in body
    assert "build_website" in body


def test_debate_skill_teaches_debate_tool_forms_and_dual_products():
    # 重构后辩论是独立的 `debate` 工具（主持人驱动），不再是 delegate 上的 stance/round 标记。
    # skill 教三形态选择、参与方配置、主持人自调轮数、双产物、与 delegate / ask_user 的边界。
    body = _body("debate_and_review")
    assert "debate" in body and "辩论" in body
    # 三形态 + 红队被审方
    assert "red_team" in body and "roundtable" in body
    assert "is_subject" in body
    # 你只定命题与参与方；轮数由主持人自调
    assert "motion" in body and "sides" in body
    # 双产物
    assert "决策简报" in body and "交锋叙事线" in body
    # 边界：并行调研仍用 delegate；收尾价值之争交 ask_user
    assert "delegate" in body and "ask_user" in body
    # 收尾铁律：别抹平证据状态 + 原样传达裁决 + 不引入场外量化（与 to_ceo_output 尾部同口径）
    assert "别抹平证据状态" in body or "既定事实" in body
    assert "升格" in body or "核实状态" in body
    assert "原样传达" in body or "保留意见" in body
    assert "不引入场外量化" in body
    assert "量化估算" in body
    # 多视角调研起源的辩论 → 指向 deep_multi_lens_research 幕 2：先真辩再跨维简报
    assert "deep_multi_lens_research" in body
    assert "跨维度" in body or "各透镜" in body
    assert "不可" in body or "跳过" in body  # 尚无完赛辩论时不可因简报形状跳过 debate
    assert "未辩先写简报" in body or "禁编造" in body or "编造" in body
    # 多视角起源时禁塌成默认「辩论收报 / 正反拍板综述」
    assert "辩论收报" in body or "正反拍板" in body
    assert "收尾分流" in body or "分维" in body
    # 薄立场：与 schema 硬校验对齐（硬上限 / 拒绝重试）
    assert "硬上限" in body or "拒绝调用" in body
    assert "论点清单" in body


def test_debate_skill_teaches_intent_alignment_before_opening():
    # §四 意图对齐（法律辩论案例的根因修复）: before opening a debate the CEO must stay
    # faithful to the user's framing — cover every pole the user named (don't silently
    # drop / swap the「减轻」pole for a milder「审慎派」), and clarify an ambiguous
    # reference the debate hinges on (「最近很火的那个」) via ask_user rather than picking
    # one reading and diving in. Pins the范式 so it can't silently regress.
    body = _body("debate_and_review")
    # ① 忠于用户点名的对立极：不得砍掉 / 偷换一极
    assert "对立极" in body
    assert "偷换" in body
    # ② 关键指代模糊先澄清，用 ask_user 确认，而非自挑一解开辩
    assert "先澄清" in body
    assert "ask_user" in body
    # ③ 形态冲突：仅纠正已有产物偷换；非跳过调研通行证（防断章引用成直辩许可）
    assert "形态冲突" in body
    assert "非跳过调研通行证" in body or "不】构成跳过前置调研" in body
    assert "已有" in body and ("motion_card" in body or "调研产物" in body)
    assert "deep_multi_lens_research" in body
    assert "模拟法庭" in body or "庭审" in body
    assert "以用户点名形态为准" in body or "用户点名形态" in body


def test_debate_skill_teaches_thin_stance():
    # stance 薄约束：CEO 只写一句话立场倾向，禁预写论点大纲 / 论证角度指令。
    # schema + Skill 对称于 background 的硬边界；防「开辩前替辩手写论证剧本」回退。
    from agentcore.tools.builtin.debate.schema import DEBATE_PARAMETERS, STANCE_MAX_CHARS

    body = _body("debate_and_review")
    assert "立场倾向" in body
    assert "一句话" in body or "单句" in body
    assert "支持一审判决正确" in body or "判赔过重" in body
    assert "核心论点" in body or "系统论证" in body
    assert "background" in body
    assert "剧本" in body or "工作产出" in body
    assert "48" not in body  # 旧字符闸口径已退役
    assert str(STANCE_MAX_CHARS) in body or "80" in body

    stance_desc = DEBATE_PARAMETERS["properties"]["sides"]["items"]["properties"]["stance"][
        "description"
    ]
    assert "一句话立场倾向" in stance_desc or "立场倾向" in stance_desc
    assert "单句" in stance_desc or "一句话" in stance_desc
    assert "background" in stance_desc
    assert "核心论点" in stance_desc or "系统论证" in stance_desc
    assert stance_desc.count(str(STANCE_MAX_CHARS)) >= 1
    assert DEBATE_PARAMETERS["properties"]["sides"]["items"]["properties"]["stance"][
        "maxLength"
    ] == STANCE_MAX_CHARS


def test_debate_skill_teaches_background_for_concrete_cases():
    # 赛前底料引导：具体案件 / 真实事件类命题建议传 background（3–5 条客观事实），
    # 纯价值观命题不必——避免双方重复检索同一批底料。Pins the引导措辞。
    body = _body("debate_and_review")
    assert "background" in body
    assert "具体案件" in body or "真实事件" in body
    assert "客观事实" in body
    assert "不必传" in body or "不必" in body


def test_revise_skill_teaches_recall_and_delegate_fallback():
    body = _body("revising_a_product")
    assert "continue_from_run_id" in body
    assert "delegate" in body
    # 调查批确认修 → 默认乙；换 title ≠ 换职能；禁再套 repair_code 冷开。
    assert "默认乙" in body or "确认按结论修" in body
    assert "不算" in body and ("换职能" in body or "title" in body)
    assert "repair_code" in body and "禁止" in body
    # 甲边界：真换职能 / 无现场 / 合并 → 冷委派 + replaces_run_id.
    assert "冷委派" in body and "replaces_run_id" in body
    assert "真换职能" in body or "非仅改 title" in body
    assert "补派" in body or "接手" in body
    # D1：乙可声明超集 tools；只读不够则扩面或冷开验证。
    assert "只增不减" in body or "超集" in body
    assert "test_run" in body
    # 修订落盘纪律：优先 str_replace / file_append；整盖允许但勿惰性省略。
    assert "str_replace" in body and "file_append" in body
    assert "file_write" in body
    assert "优先" in body
    assert "中间省略" in body
    assert "全文重写" not in body
    assert "**禁止**对已有成篇成品再 `file_write`" not in body
    assert "禁止骨架/最小实现" not in body


def test_team_orchestration_skill_teaches_revision_local_edit():
    body = _body("team_orchestration_advanced")
    assert "有界返工环" in body
    assert "str_replace" in body
    assert "中间省略" in body or "已保留首尾" in body


def test_ask_user_kickoff_skill_teaches_short_clarify():
    skill = build_system_skill_registry().get("ask_user_kickoff")
    assert skill.requires_tools == ("ask_user",)
    body = skill.body
    assert "assumptions" in body
    assert "questions" in body
    assert "style_options" in body  # 兼容字段说明
    assert "短问" in body or "短澄清" in body
    assert "开工提案卡" not in body
    assert "提案体硬闸" not in body
    assert "一键开做" not in body or "禁止" in body
    assert "checkpoint_after" not in body


def test_ask_user_kickoff_skill_mentions_compat_options_not_ledger():
    body = _body("ask_user_kickoff")
    assert "format_options" in body
    assert "不记账" in body or "不硬闸" in body
    assert "style_options" in body


def test_ask_user_kickoff_skill_teaches_software_delivery_not_default_html():
    body = _body("ask_user_kickoff")
    assert "软件" in body or "应用" in body
    assert "交付形态" in body
    assert "单 HTML" in body
    assert "build_feature" in body or "build_app" in body


def test_ask_user_midtask_skill_teaches_fork_annotate_and_nonblocking():
    # 途中拍板 split: the mid-task fork + 何时不打断 (proceed-and-annotate) + the
    # non-blocking ask + debate closing handed to the user. Gated on ask_user; the
    # checkpoint mechanism is now its own skill, not part of midtask.
    skill = build_system_skill_registry().get("ask_user_midtask")
    assert skill.requires_tools == ("ask_user",)
    body = skill.body
    assert "采纳正方" in body  # debate closing handed to the user
    assert "假设" in body and "若不符请指正" in body  # proceed-and-annotate
    assert "blocking=false" in body  # the non-blocking ask
    assert "checkpoint_after" not in body
    # 定向修订委派须写明局部改纪律（risk_ack → 有界返工环）。
    assert "str_replace" in body
    assert "中间省略" in body or "file_write" in body
    # 定案 A：优化项目 ≠ 默认催 open_local_project；附件收窄范围时先干活。
    assert "open_local_project" in body
    assert "≠默认开项目卡" in body or "收窄本轮" in body
    assert "开工前置" in body
    # 已绑定本地工程：「打开项目」=跑当前项目，换目录才开卡。
    assert "已绑定本地工程" in body
    assert "跑" in body and "当前" in body
    # Web 假确认修复：引导桌面下载 + 未见挂载勿称已确认
    assert "https://fashitianxia.xyz/download" in body
    assert "授权已确认" in body
    assert "本对话已授权区外目录" in body


def test_delegate_checkpoint_skill_teaches_wave_boundary_pause():
    # 委派波间挂起 split out: the checkpoint_after wave-boundary pause. Gated on
    # ask_user (the live-user proxy) since it pauses for user review.
    skill = build_system_skill_registry().get("delegate_checkpoint")
    assert skill.requires_tools == ("ask_user",)
    body = skill.body
    assert "checkpoint_after" in body
    assert "depends_on" in body  # only meaningful inside a multi-step DAG
    # B1 轻教法：用户明文要把关 → 必用结构化卡，禁止纯聊天代卡。
    assert "明文要求" in body
    assert "必用" in body
    assert "禁止纯聊天" in body
    assert "research_report" in body


def test_verify_and_fix_skill_teaches_test_run_loop():
    skill = build_system_skill_registry().get("verify_and_fix")
    # Gated on delegate (the delegated dev loop), not test_run — test_run is now a
    # worker-only execution tool and consult_skill is CEO-only, so gating on it would
    # make the skill un-advertisable. The body still teaches the test_run → fix loop.
    assert skill.requires_tools == ("delegate",)
    body = skill.body
    assert "test_run" in body
    assert "str_replace" in body
    assert "escalate" in body
    # 阶段3：编辑以磁盘为真源；禁骨架 file_write 冒充修复
    assert "磁盘" in body
    assert "骨架" in body
    assert "file_write" in body


def test_long_form_writing_skill_teaches_skeleton_fill():
    skill = build_system_skill_registry().get("long_form_writing")
    assert skill.requires_tools == ("delegate",)
    body = skill.body
    assert "file_write" in body
    assert "file_append" in body
    assert "大纲" in body
    assert "骨架" in body
    assert "Artifact-first" in body or "骨架填空" in body
    assert "file_read 抽查" not in body
    assert "manifest" in body
    assert "code_execute" in body
    assert "handoff" in body
    assert "禁止" in body and "file_read" in body
    assert "禁止" in body and ("整篇一次" in body or "一次 file_write" in body)
    assert "连续写失败" in body or "分段写" in body
    # B1 轻教法：明文把关 → checkpoint_after / research_report；自主确认才可对话式。
    assert "明文要求" in body
    assert "checkpoint_after" in body
    assert "research_report" in body
    # 与多角协作划界：A parallel_brief / B research_report；材料已齐才单写手
    assert "划界" in body
    assert "parallel_brief" in body
    assert "材料已齐" in body
    assert "角 prose" in body and "仅主笔落盘" in body
    assert "纯聊天" in body
    assert "自主确认" in body or "轻量" in body
    # 论文并行拆章：单主文件 + 合并责任（禁各写各的就交）；不误伤多产物。
    assert "单主文件" in body or "同一主文件" in body or "最终主文件" in body
    assert "合并责任" in body or "merge" in body.lower()
    assert "各写各的" in body
    assert "建站" in body
    # MD→PDF：主交付 .md；要分享时 md_to_pdf；禁 HTML/reportlab 主路径
    assert "md_to_pdf" in body
    assert "HTML" in body
    assert "reportlab" in body
    assert "单主文件" in skill.summary or "合并" in skill.summary
    assert "骨架" in skill.summary or "禁止整篇" in skill.summary


def test_deep_multi_lens_research_listed_and_gated_on_delegate():
    skill = build_system_skill_registry().get("deep_multi_lens_research")
    assert skill is not None
    assert skill.requires_tools == ("delegate",)
    directory = render_skill_directory(build_system_skill_registry(), _NO_LIVE_USER)
    assert "deep_multi_lens_research" in directory
    assert skill.summary in directory


def test_deep_multi_lens_research_teaches_parallel_lenses_and_motion_card():
    body = _body("deep_multi_lens_research")
    assert "法律" in body and "品牌商业" in body
    assert "舆情公关" in body and "文化社会" in body
    assert "depends_on" in body
    assert "multi_lens_research" in body
    assert "motion_card" in body
    assert "handoff" in body
    # 幕 1 案卷落盘：research/ + form=files / artifacts（叠加 handoff，不替代）
    assert "AgentCore/文档/research/" in body
    assert "透镜报告" in body
    assert "汇总与命题卡" in body
    assert "form=files" in body or "form\": \"files\"" in body or "`form=files`" in body
    assert "artifacts" in body
    assert "叠加" in body or "不得替代" in body
    # 薄立场 + rationale 铁律（与 debate_and_review / motion_card 契约相容）
    assert "薄立场" in body or "一句话" in body
    assert "48" not in body  # 旧字符闸口径已退役
    assert "rationale" in body
    assert "继续调研" in body or "对抗检验" in body
    assert "见分歧" in body  # 严禁见分歧就建议开辩
    assert "真对立轴" in body  # 存在真对立轴则必须产卡
    # CEO 禁止自搜替代四路；先调研后辩；探路 query 建议短查（工具会截断过长）
    assert "5 轮" in body
    assert "禁止自搜" in body or ("禁止" in body and "替代四路" in body)
    assert "截断" in body or "规范化" in body
    assert "≤8 词" not in body
    assert "本回合" in body and "debate" in body
    assert "用户同意" in body or "批准" in body
    # 批 B：推进卡即授权；勿口头征求、勿本回合自调 debate
    assert "阶段推进卡" in body or "推进卡" in body
    assert "勿口头征求" in body
    # 任务书须点名结构化字段；禁 markdown / Followups 旁路
    assert "handoff.motion_card" in body or "对象字段" in body
    assert "markdown" in body.lower() or "正文" in body
    assert "Followups" in body or "芯片" in body or "推进卡" in body
    # 幕 2：先真辩完赛再跨维简报；已辩才可复用；赛况忠实禁编造；不抹平证据/裁决
    assert "先辩后报" in body or "先真辩" in body
    assert "跨维度" in body or "各透镜" in body
    assert "跳过" in body and "debate" in body  # 禁因简报形状跳过 debate
    assert "已辩复用" in body or "不重开辩" in body
    assert "编造" in body
    assert "辩论收报" in body or "正反拍板" in body  # 禁塌成默认辩后收尾
    assert "分维" in body or "小标题" in body
    assert "待核实" in body or "保留" in body
    # 引用即出处 P3：透镜成稿主张须证 + 汇总继承（prompt 软约束；不强迫辩词二分）。
    assert "主张" in body or "关键数字" in body or "关键结论" in body
    assert "#rN" in body
    assert "不强迫" in body or "二分" in body
    assert "继承" in body and ("#rN" in body or "待核实" in body)
    # 入口分流：调研意图走本 skill；点名开辩勿抢拦（分流句前置）
    assert "入口分流" in body or "按意图" in body
    assert "debate_and_review" in body
    assert "直调" in body or "勿" in body
    assert "也可直接开辩" in body or "意图模糊" in body
    # 超笼统调研输入仍先 ask 确认再挂 playbook
    assert "ask_user" in body
    assert "确认" in body and ("启动" in body or "多视角" in body)
    # 命题保真：收卡呈报前校验；延伸辩题不得替换主命题
    assert "命题保真" in body
    assert "延伸辩题" in body
    assert "替换主命题" in body or "替换" in body
    # 批 D+：透镜检索分工——首透镜查全公共底料，其余盯独有缺口（并行静态分工）
    assert "检索分工" in body
    assert "首个透镜" in body or "首透镜" in body
    assert "简要确认" in body
    assert "独有" in body
    assert "并行" in body
    # 检索额度统一默认（不再半格差异化）
    assert "统一默认" in body or "同额" in body
    assert "半格" not in body
    assert "略高" not in body
    assert "差异化" not in body


def test_deep_multi_lens_research_summary_intent_routing():
    """目录摘要钉 WHEN；入口分流长文在 body，勿复述核心长文。"""
    deep = build_system_skill_registry().get("deep_multi_lens_research")
    assert deep is not None
    summary = deep.summary
    assert "调研" in summary or "研究" in summary
    assert "debate_and_review" in summary
    assert "抢拦" in summary
    assert "模拟法庭" in summary or "庭审对抗" in summary or "对簿公堂" in summary
    # 长分流教法在 body
    assert "入口分流" in deep.body
    assert "同句点名终局对抗仍先取证" not in summary


def test_named_debate_routes_to_debate_not_mlr():
    """点名开辩 / 模拟庭审 / 终局对抗 → debate_and_review 直调 debate，勿 MLR 抢拦。"""
    debate = build_system_skill_registry().get("debate_and_review")
    deep = build_system_skill_registry().get("deep_multi_lens_research")
    assert debate is not None and deep is not None
    assert "入口分流" in debate.body or "按意图" in debate.body
    assert "直调" in debate.body and "debate" in debate.body
    assert "庭前取证" in debate.body or "辩论机制" in debate.body
    # summary 只 WHEN，不复述核心长分流
    assert "deep_multi_lens_research" in debate.summary
    assert "debate_and_review" in deep.summary
    assert "抢拦" in deep.summary or "勿" in deep.body
    assert "同句点名终局对抗仍先取证" not in deep.summary
    assert "同句点名" not in deep.body or "仍【先】" not in deep.body


def test_research_intent_routes_to_mlr():
    """调研 / 研究意图 → deep_multi_lens_research（body 钉分流；summary 点 WHEN）。"""
    debate = build_system_skill_registry().get("debate_and_review")
    deep = build_system_skill_registry().get("deep_multi_lens_research")
    assert debate is not None and deep is not None
    for text in (debate.body, deep.body, debate.summary, deep.summary):
        assert "调研" in text or "研究" in text
    assert "deep_multi_lens_research" in debate.summary
    assert "deep_multi_lens_research" in debate.body
    assert "平行取证" in deep.summary or "平行取证" in deep.body
    assert "命题卡" in deep.summary or "motion_card" in deep.body
    # 模糊意图：保守走 MLR + 提示也可直接开辩
    assert "意图模糊" in debate.summary or "意图模糊" in debate.body
    assert "也可直接开辩" in debate.summary or "也可直接开辩" in debate.body
    assert "也可直接开辩" in deep.summary or "也可直接开辩" in deep.body


def test_deep_multi_lens_research_summary_forbids_ceo_solo_search():
    """防 CEO 自搜替代四路：summary 点 WHEN；细则在 body。"""
    deep = build_system_skill_registry().get("deep_multi_lens_research")
    assert deep is not None
    assert "自搜" in deep.body or "禁止" in deep.body
    assert "playbook" in deep.body


def test_debate_and_review_summary_intent_routes_research_to_mlr():
    """目录 WHEN：调研归 MLR；分流长文在 body。"""
    debate = build_system_skill_registry().get("debate_and_review")
    assert debate is not None
    summary = debate.summary
    assert "deep_multi_lens_research" in summary
    assert "调研" in summary or "研究" in summary
    assert "入口分流" in debate.body or "按意图" in debate.body
    assert "直调" in debate.body and "debate" in debate.body
    # 旧「除外·公共事件先走 MLR（含模拟法庭终局）」口径已退役
    assert "除外" not in summary or "模拟法庭类终局诉求" not in summary


def test_legal_case_analysis_summary_excludes_public_mock_court():
    """目录除外：公共品牌/舆论模拟法庭不归 legal_case_analysis 抢触发。"""
    legal_reg = build_system_skill_registry(include_legal=True)
    case = legal_reg.get("legal_case_analysis").summary
    assert "除外" in case
    assert "模拟法庭" in case
    assert "多维取证" in case
    assert "deep_multi_lens_research" in case
    # 除外须前置：避免「先对抗后研判」抢在商标/模拟法庭议题上先匹配。
    assert case.index("除外") < case.index("先对抗后研判")


def test_legal_case_analysis_body_redirects_public_mock_court_to_mlr():
    """正文须与目录除外同口径：consult 后仍能把公共模拟法庭打回 MLR。"""
    legal_reg = build_system_skill_registry(include_legal=True)
    body = legal_reg.get("legal_case_analysis").body
    assert "模拟法庭" in body
    assert "deep_multi_lens_research" in body
    assert "multi_lens_research" in body
    assert "停止" in body or "勿用本 skill" in body or "不走本 skill" in body


def test_deep_multi_lens_and_legal_summaries_are_mutually_exclusive():
    """目录触发分流：legal 系 vs 多维公共事件——互斥动词域，避免商标案抢触发。"""
    deep = build_system_skill_registry().get("deep_multi_lens_research")
    legal_reg = build_system_skill_registry(include_legal=True)
    legal_summaries = [
        legal_reg.get("legal_case_analysis").summary,
        legal_reg.get("legal_answer_brief").summary,
    ]
    # 新 skill：多维公共事件 / 先平行取证 / 命题卡 / 批准再辩
    for marker in ("多维公共事件", "平行取证", "命题卡"):
        assert marker in deep.summary, marker
        for ls in legal_summaries:
            assert marker not in ls, (marker, ls)
    assert "批准再辩" in deep.summary
    for ls in legal_summaries:
        assert "批准再辩" not in ls
    # legal：律师作业 / 接案或文书 / 先对抗后研判（或对抗再核验）
    for ls in legal_summaries:
        assert "律师作业" in ls
    case = legal_reg.get("legal_case_analysis").summary
    assert "接案" in case or "诉讼策略" in case
    assert "先对抗后研判" in case
    for marker in ("律师作业", "接案", "诉讼策略", "先对抗后研判"):
        assert marker not in deep.summary, marker
