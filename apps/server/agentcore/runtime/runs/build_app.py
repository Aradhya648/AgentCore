"""绿场软件 / SPA 完整交付 playbook（scaffold-first 多波 → 结构完整性 → 诚实交付）.

独立模块，避免再胀 ``playbooks.py``。对标 ``build_website`` 硬锁模式：五阶段串起、
禁单 worker 包整站；``form=files`` + ``strict``；顶层批次由调用方设 criteria
（含自动 ``graph_consistent``）。

默认瘦启动：仅 1 个业务模块（scaffold+shared+1×module+integrate+smoke = 5 节点）；
显式 ``modules`` 经 ``fold_fanout_slots`` 折叠，禁止一次铺满多人。
"""

from __future__ import annotations

import re
from typing import Any

from agentcore.runtime.runs.playbooks._common import fold_fanout_slots

_DEFAULT_STACK = "Vue3+Vite+TS"
# 瘦启动：默认只铺一个关键业务模块（阶段仍齐全，勿默认双模块并行）。
_DEFAULT_MODULES = ("总览页",)
# 模块扇出硬顶（playbook 本地 cap，非全局 max_parallel）。
_MAX_MODULE_FANOUT = 3

_SLUG_RE = re.compile(r"[^\w\-]+", re.UNICODE)
_CJK_SLUG_RE = re.compile(r"[\u4e00-\u9fff]+")


def _clean_str(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _clean_str_list(value: Any, *, cap: int | None = None) -> list[str]:
    if not isinstance(value, list):
        return []
    out: list[str] = []
    for item in value:
        s = item.strip() if isinstance(item, str) else ""
        if s and s not in out:
            out.append(s)
        if cap is not None and len(out) >= cap:
            break
    return out


def _derive_root(app: str, root_slot: str) -> str:
    """Project directory under workspace: slot ``root`` or short slug from ``app``."""
    if root_slot:
        return root_slot.strip().strip("/").replace("\\", "/")
    # Prefer a short ASCII-ish slug; fall back to a stable Chinese-trimmed name.
    ascii_bits = _SLUG_RE.sub("-", app.lower()).strip("-")
    ascii_bits = re.sub(r"-{2,}", "-", ascii_bits)[:32].strip("-")
    if ascii_bits and any(c.isascii() and c.isalnum() for c in ascii_bits):
        return ascii_bits
    cjk = "".join(_CJK_SLUG_RE.findall(app))[:12]
    return cjk or "app"


def _module_id(index: int) -> str:
    return f"module_{index}"


def _page_path(root: str, mod: str, index: int) -> str:
    page_slug = _derive_root(mod, "") or f"module-{index}"
    return f"{root}/src/views/{page_slug}.vue"


def _build_app(args: dict[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    """scaffold → shared → N×module_* → integrate → smoke.

    Slots: ``app``(required) / ``modules``(optional) / ``stack``(optional) / ``root``(optional).
    Default modules = 1（瘦启动）；显式 modules 经 fold 压到 ≤``_MAX_MODULE_FANOUT`` 槽。
    """
    app = _clean_str(args.get("app"))
    if not app:
        return [], ["build_app 需要 slot『app』（要搭建的应用 / SPA 简述）"]

    modules = _clean_str_list(args.get("modules"), cap=None)
    if not modules:
        modules = list(_DEFAULT_MODULES)

    module_slots, fold_note = fold_fanout_slots(
        modules, limit=_MAX_MODULE_FANOUT, label="功能模块"
    )
    fold_hint = f" {fold_note}" if fold_note else ""

    stack = _clean_str(args.get("stack")) or _DEFAULT_STACK
    root = _derive_root(app, _clean_str(args.get("root")))
    stack_hint = f"（技术栈：{stack}）"

    # Stub pages for every *logical* module (pre-fold) — router must not dangle even when
    # several modules fold into one worker.
    stub_pages: list[str] = []
    for i, mod in enumerate(modules):
        stub_pages.append(_page_path(root, mod, i))

    scaffold_artifacts = [
        f"{root}/package.json",
        f"{root}/vite.config.ts",
        f"{root}/tsconfig.json",
        f"{root}/tsconfig.node.json",
        f"{root}/index.html",
        f"{root}/src/main.ts",
        f"{root}/src/App.vue",
        f"{root}/src/router/index.ts",
        *stub_pages,
    ]
    stub_list = "、".join(f"`{p}`" for p in stub_pages)

    iron_rule = (
        "【铁律·同波闭合】router / 入口引用的每个页面文件必须在本波同批创建"
        "（可先 stub 空壳组件），禁止悬空 import；缺页=结构缺口，不得留死链。"
    )

    tasks: list[dict[str, Any]] = [
        {
            "id": "scaffold",
            "role": "脚手架工程师",
            "task": (
                f"为应用【{app}】在 `{root}/` 落下 Vite+TS 脚手架{stack_hint}："
                f"`package.json`、`vite.config.ts`、`tsconfig.json` / `tsconfig.node.json`、"
                f"`index.html`、`src/main.ts`、`src/App.vue`、`src/router/index.ts`"
                "（或等价入口路由）。"
                f"{iron_rule}"
                f"路由表必须挂上全部模块占位页，并同波写出 stub 文件：{stub_list}。"
                "用 file_write 落盘；勿在本步实现业务逻辑。"
            ),
            "deliverable": {
                "form": "files",
                "name": f"Vite+TS 脚手架（已落盘 {root}/，含模块 stub）",
                "artifacts": scaffold_artifacts,
                "strict": True,
            },
        },
        {
            "id": "shared",
            "role": "公共层工程师",
            "task": (
                f"在 `{root}/` 设计 token / 公共组件 / store（按技术栈 {stack} 提示）"
                f"为应用【{app}】打底。"
                "只写可复用层，勿包办各业务模块页面正文。"
                "用 file_write 落盘；import 图须闭合（被引用文件同波创建）。"
            ),
            "depends_on": ["scaffold"],
            "deliverable": {
                "form": "files",
                "name": f"设计 token / 公共组件 / store（{root}/src）",
                "artifacts": [
                    f"{root}/src/styles/tokens.css",
                    f"{root}/src/components/AppButton.vue",
                    f"{root}/src/stores/app.ts",
                ],
                "strict": True,
            },
        },
    ]

    module_ids: list[str] = []
    # Stable index into the pre-fold module list for page path derivation.
    flat_index = 0
    for slot_i, parts in enumerate(module_slots):
        mid = _module_id(slot_i)
        module_ids.append(mid)
        merged = len(parts) > 1
        label = " + ".join(parts)
        page_paths: list[str] = []
        for part in parts:
            page_paths.append(_page_path(root, part, flat_index))
            flat_index += 1
        module_desc = (
            f"合并模块：{'、'.join(f'【{p}】' for p in parts)}（须全部覆盖）"
            if merged
            else parts[0]
        )
        path_hint = "、".join(f"`{p}`" for p in page_paths)
        body: dict[str, Any] = {
            "id": mid,
            "role": f"{label}实现",
            "task": (
                f"实现{module_desc}（应用【{app}】）{stack_hint}："
                f"在 `{root}/src/` 下落盘本槽页面与必要子组件；"
                f"建议主文件 {path_hint}（可按 stack 调整扩展名）。"
                "严格对接上游 scaffold 路由与 shared 公共层；"
                "发现契约缺口用 post_note(kind=heads_up)，勿静默改脚手架约定。"
                "本节点只做本槽模块，禁止包办其它槽或另起平行整站。"
                f"{fold_hint}"
            ),
            "depends_on": ["shared"],
            "deliverable": {
                "form": "files",
                "name": f"模块【{label}】源码",
                "artifacts": page_paths,
                "strict": True,
            },
        }
        if fold_note and merged:
            body["playbook_note"] = fold_note
        tasks.append(body)

    tasks.append(
        {
            "id": "integrate",
            "role": "集成工程师",
            "task": (
                f"接线应用【{app}】（`{root}/`）：核对 router ↔ 各模块页面、"
                "删死链、保证相对路径与 `@/`（→ src/）import 图闭合。"
                "缺文件必须补齐 stub 或修正引用，禁止留下悬空 import。"
                "用 file_write / str_replace 落盘修订。"
            ),
            "depends_on": list(module_ids),
            "deliverable": {
                "form": "files",
                "name": f"已闭合的路由与 import 图（{root}/）",
                "artifacts": [
                    f"{root}/src/router/index.ts",
                    f"{root}/src/App.vue",
                ],
                "strict": True,
            },
        }
    )

    tasks.append(
        {
            "id": "smoke",
            "role": "冒烟验收",
            "task": (
                f"对 `{root}/` 做冒烟：优先云端 `test_run`——"
                "`check=install`（或 check=command + npm/pnpm/yarn install）再 "
                "`check=build`（或 typecheck / vue-tsc）；"
                "装包需受限出网，失败则诚实走结构自检（import 图 / graph_consistent）"
                "并写明缺口，勿空转、勿改道 code_execute 跑 npm install。"
                "结果与缺口写入 QA 笔记落盘。只报告与最小修补，勿重写整站。"
            ),
            "depends_on": ["integrate"],
            "deliverable": {
                "form": "files",
                "name": f"冒烟 / QA 笔记（{root}/QA.md）",
                "artifacts": [f"{root}/QA.md"],
                "requires_files": True,
            },
            "timeout_ms": 300_000,
        }
    )
    return tasks, []
