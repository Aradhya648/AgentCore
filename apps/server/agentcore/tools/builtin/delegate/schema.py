"""Delegate tool schema and constants.

Schema layer (工具面瘦身): short trigger + key param cues only. Routing judgment
lives in the CEO core; advanced HOW lives in ``consult_skill(team_orchestration_advanced)``.
"""

from __future__ import annotations

from agentcore.runtime.runs.constants import MAX_DELEGATION_TASKS
from agentcore.runtime.runs.playbooks import PLAYBOOKS

# Shared task-level deliverable shape (delegate tasks + replan binds/add).
TASK_DELIVERABLE_SCHEMA: dict[str, object] = {
    "type": "object",
    "description": "可选交付物（form 等）。细节见 team_orchestration_advanced。",
    "properties": {
        "name": {"type": "string"},
        "form": {
            "type": "string",
            "enum": ["prose", "files"],
            "description": "prose=看；files=用（须落盘）。",
        },
        "required_sections": {"type": "array", "items": {"type": "string"}},
        "must_contain": {"type": "array", "items": {"type": "string"}},
        "min_length": {"type": "integer"},
        "max_length": {"type": "integer"},
        "output_format": {"type": "string", "enum": ["text", "json"]},
        "requires_files": {"type": "boolean"},
        "artifacts": {"type": "array", "items": {"type": "string"}},
        "artifact_dir": {
            "type": "string",
            "description": (
                "案卷落盘目录（可选；可多人共享；省略时运行时按 stage_dirs 填默认）。"
                "目录不占归属；并行互斥靠各人不同的 artifacts 文件路径。"
            ),
        },
        "strict": {
            "type": "boolean",
            "description": "不达标：true=硬退；false=软接受。",
        },
    },
}

# Trigger + short cues. Long HOW → CEO core / team_orchestration_advanced.
DELEGATE_DESCRIPTION = (
    f"拆任务给临时团队（tasks：role+task，≤{MAX_DELEGATION_TASKS}；非终结）。"
    "该派就派；按活的缝拆人、能少则少；闲聊/单点/聊天短文自己答；要落盘短文派1人。"
    "交付形态：给用户【看】→deliverable.form=prose；【用】→form=files。"
    "多任务先判生产者→消费者；互不依赖才平铺并行。"
    "≥2 worker 默认协调（立即返回、可同回合追加同一张图）。"
    "跨回合加人 append_to_execution_id=\"latest\"。"
    "playbook 可选（建站必须 build_website/build_toolshed；其余可省略直接手写 tasks）；与 tasks 二选一。"
    "completion_criteria 仅顶层（勿写入 tasks[]）。"
    "拿不准怎么拆再 consult_skill(team_orchestration_advanced)。"
)

DELEGATE_PARAMETERS = {
    "type": "object",
    "properties": {
        "tasks": {
            "type": "array",
            "description": f"子任务（≤{MAX_DELEGATION_TASKS}）。",
            "items": {
                "type": "object",
                "properties": {
                    "role": {"type": "string"},
                    "task": {
                        "type": "string",
                        "description": "自包含任务；worker 看不到完整历史。",
                    },
                    "objective": {"type": "string"},
                    "deliverable": TASK_DELIVERABLE_SCHEMA,
                    "stance": {"type": "string", "enum": ["pro", "con"]},
                    "group": {"type": "string"},
                    "round": {"type": "integer"},
                    "id": {"type": "string"},
                    "depends_on": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": (
                            "依赖任务 id（DAG）。"
                            "填同一次 tasks 的 id 字段字面值或无歧义角色名；禁 del_*。"
                            "何时填（生产者→消费者）见系统提示路由。"
                        ),
                    },
                    "result_handling": {
                        "type": "string",
                        "enum": ["pass_through", "summarize"],
                    },
                    "replaces_run_id": {"type": "string"},
                    "continue_from_run_id": {"type": "string"},
                    "checkpoint_after": {"type": "boolean"},
                    "bind_after_deps": {"type": "boolean"},
                    "require_upstream": {
                        "type": "boolean",
                        "description": "false=≥1 上游成功即跑；true=须全量。",
                    },
                    "force_continue": {"type": "boolean"},
                },
                "required": ["role", "task"],
            },
        },
        "finalize": {"type": "boolean"},
        "append_to_execution_id": {
            "type": "string",
            "description": "跨回合追加：\"latest\" 或 execution_id。",
        },
        "coordinate": {
            "type": "boolean",
            "default": True,
            "description": "协调（默认 true）；false=阻塞。",
        },
        "force": {"type": "boolean", "default": False},
        "playbook": {
            "type": "string",
            "enum": sorted(PLAYBOOKS),
            "description": (
                "可选固化形状名（与 tasks 二选一：传此字段时勿再传 tasks，"
                "槽位进 playbook_args）。建站/落地页必须 build_website；"
                "控制台/工具台 dense 必须 build_toolshed；其余自由组队可省略，"
                "直接手写 tasks。亦可用 playbook_id。"
            ),
        },
        "playbook_id": {
            "type": "string",
            "description": (
                "可选 playbook 声明：已知形状名，或字面值 \"none\"（手写 tasks）。"
                "与 playbook 同义优先。建站意图禁止 none/手写旁路；"
                "软件意图禁止 none+单前端单 HTML 薄旁路。"
            ),
        },
        "playbook_none_reason": {
            "type": "string",
            "description": (
                "可选：手写 tasks 时一句说明（不强制）。"
                "软件意图禁止仅因单文件缩成 1 名前端 + 单 HTML。"
            ),
        },
        "playbook_args": {"type": "object"},
        "coordination": {
            "type": "string",
            "enum": ["wall", "none"],
            "default": "none",
        },
        "seed_notes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {
                        "type": "string",
                        "enum": ["decision", "heads_up", "claim"],
                    },
                    "text": {"type": "string"},
                },
                "required": ["text"],
            },
        },
        "team_brief": {"type": "string"},
        "complexity_hint": {
            "type": "string",
            "enum": ["light", "standard"],
        },
        "parallelism": {
            "type": "string",
            "enum": ["conservative", "balanced", "aggressive"],
        },
        "completion_criteria": {
            "description": (
                "批次验收（仅 delegate 顶层，与 tasks 同级；"
                "勿写入 tasks[] 元素——多 task 内嵌且值不同会被拒）。"
            ),
            "oneOf": [
                {
                    "type": "string",
                    "enum": ["files_written", "code_verified"],
                },
                {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": ["custom"]},
                        "description": {"type": "string"},
                    },
                    "required": ["type"],
                },
            ],
        },
    },
}
