"""阶段产物（案卷）目录约定 —— 后端单一权威源。

工作区相对路径：``AgentCore/文档/{research,debate,reviews}/``。
仅工作区盘；**永不**进 documents / ``<rules>`` 注入（见记忆 §5.0）。
开发期直切，无根级旧路径兼容。
"""

from __future__ import annotations

AGENTCORE_ROOT = "AgentCore"
DOCS_DIR_NAME = "文档"
DOCS_PREFIX = f"{AGENTCORE_ROOT}/{DOCS_DIR_NAME}"

RESEARCH_DIR = f"{DOCS_PREFIX}/research"
DEBATE_DIR = f"{DOCS_PREFIX}/debate"
REVIEWS_DIR = f"{DOCS_PREFIX}/reviews"

RESEARCH_PREFIX = f"{RESEARCH_DIR}/"
DEBATE_PREFIX = f"{DEBATE_DIR}/"
REVIEWS_PREFIX = f"{REVIEWS_DIR}/"

__all__ = [
    "AGENTCORE_ROOT",
    "DOCS_DIR_NAME",
    "DOCS_PREFIX",
    "RESEARCH_DIR",
    "DEBATE_DIR",
    "REVIEWS_DIR",
    "RESEARCH_PREFIX",
    "DEBATE_PREFIX",
    "REVIEWS_PREFIX",
]
