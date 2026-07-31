"""阶段产物（案卷）目录约定 —— 后端单一权威源。

工作区相对路径：``AgentCore/文档/{research,debate,reviews,项目}/``。
仅工作区盘；**永不**进 documents / ``<rules>`` 注入（见记忆 §5.0）。
``文档/项目/`` = 厚案卷（探索 pending 不写；闸清后/普通回合按需落盘）。
开发期直切，无根级旧路径兼容。

同树旁路（系统噪音，对 AI 与用户文件 UI 都隐藏；**不**注入）::

    AgentCore/{index,trash,baselines}/

与可见 ``规则/`` · ``记忆/`` · ``文档/`` 同根；勿与容器路径
``~/Documents/AgentCore/`` 混淆。禁止把裸名 ``index``/``trash``/``baselines``
放进全局忽略集（误伤用户项目）——须路径感知（见 ``_paths.is_internal_zone_relpath``）。
"""

from __future__ import annotations

AGENTCORE_ROOT = "AgentCore"
DOCS_DIR_NAME = "文档"
DOCS_PREFIX = f"{AGENTCORE_ROOT}/{DOCS_DIR_NAME}"

RESEARCH_DIR = f"{DOCS_PREFIX}/research"
DEBATE_DIR = f"{DOCS_PREFIX}/debate"
REVIEWS_DIR = f"{DOCS_PREFIX}/reviews"
# Thick project dossiers (导航/主题 are short; this holds long-form). Not injected.
PROJECT_DOCS_DIR = f"{DOCS_PREFIX}/项目"

RESEARCH_PREFIX = f"{RESEARCH_DIR}/"
DEBATE_PREFIX = f"{DEBATE_DIR}/"
REVIEWS_PREFIX = f"{REVIEWS_DIR}/"
PROJECT_DOCS_PREFIX = f"{PROJECT_DOCS_DIR}/"

# Machine-readable bypass under the same AgentCore/ root (system noise).
INTERNAL_ZONE_NAMES: frozenset[str] = frozenset({"index", "trash", "baselines"})
INDEX_REL = f"{AGENTCORE_ROOT}/index"
TRASH_REL = f"{AGENTCORE_ROOT}/trash"
BASELINES_REL = f"{AGENTCORE_ROOT}/baselines"

__all__ = [
    "AGENTCORE_ROOT",
    "DOCS_DIR_NAME",
    "DOCS_PREFIX",
    "RESEARCH_DIR",
    "DEBATE_DIR",
    "REVIEWS_DIR",
    "PROJECT_DOCS_DIR",
    "RESEARCH_PREFIX",
    "DEBATE_PREFIX",
    "REVIEWS_PREFIX",
    "PROJECT_DOCS_PREFIX",
    "INTERNAL_ZONE_NAMES",
    "INDEX_REL",
    "TRASH_REL",
    "BASELINES_REL",
]
