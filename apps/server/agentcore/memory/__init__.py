"""Memory system.

Layers (see docs/03-AI核心/Agent记忆与知识系统.md; two-layer long-term refactor):
- working memory: in-memory conversation history + per-turn run state (runtime data)
- episodic long-term: per-session ≤200-char digests under ``情景/`` (consolidation input only)
- semantic long-term: 偏好/画像/主题 files, maintained by batch consolidation + ``remember``

Plus auto conversation titles (a sidebar UX feature, not a memory layer).
"""

from agentcore.memory.conversation_title import (
    TITLE_MAX_CHARS,
    ChatMessage,
    LLMTitleGenerator,
    TitleGenerator,
    TitleInput,
    TitleResult,
)
from agentcore.memory.document_store import DocumentMemoryStore
from agentcore.memory.episodic import (
    EpisodeRecord,
    clamp_summary,
    should_run_semantic,
)
from agentcore.memory.followups import (
    FOLLOWUPS_ITEM_MAX_CHARS,
    FOLLOWUPS_MAX,
    FollowupInput,
    FollowupsGenerator,
    LLMFollowupsGenerator,
    format_motion_card_followup,
    merge_motion_card_followup,
    select_motion_card_from_journal,
)
from agentcore.memory.injection import MemoryTopic, load_injected_memory, load_memory_topics
from agentcore.memory.maintenance import MemoryUpdateItem, maintain_user_memory
from agentcore.memory.rules_injection import (
    RuleFragment,
    append_user_rule,
    append_user_rule_bullet,
    assemble_injected_rules,
    assemble_turn_rules,
    compose_injected_rules,
)
from agentcore.memory.store import (
    ALWAYS_MEMORY_FILES,
    CORE_MEMORY_FILE,
    EPISODIC_DIR,
    NAVIGATION_MEMORY_FILE,
    PREFERENCES_MEMORY_FILE,
    TOPIC_DIR,
    FileMemoryStore,
    MemoryFileMeta,
    MemoryScope,
    MemoryStore,
    default_file_memory_store,
    default_memory_store,
    episodic_path,
    is_episodic_path,
    is_topic_path,
    memory_version,
    topic_path,
    topic_slug,
)
from agentcore.memory.user_memory import (
    MEMORY_SECTIONS,
    PREFERENCES_SECTIONS,
    PROFILE_SECTIONS,
    LLMMemoryExtractor,
    MarkdownMemoryApplier,
    MemoryAction,
    MemoryApplier,
    MemoryExtractInput,
    MemoryExtractor,
    MemoryOp,
    core_file_for_section,
    merge_global_core,
    parse_memory_ops,
    split_global_core,
)

__all__ = [
    "ChatMessage",
    "TitleInput",
    "TitleResult",
    "TitleGenerator",
    "LLMTitleGenerator",
    "TITLE_MAX_CHARS",
    "FollowupInput",
    "FollowupsGenerator",
    "LLMFollowupsGenerator",
    "FOLLOWUPS_MAX",
    "FOLLOWUPS_ITEM_MAX_CHARS",
    "format_motion_card_followup",
    "merge_motion_card_followup",
    "select_motion_card_from_journal",
    "MEMORY_SECTIONS",
    "PREFERENCES_SECTIONS",
    "PROFILE_SECTIONS",
    "core_file_for_section",
    "MemoryAction",
    "MemoryOp",
    "MemoryExtractInput",
    "MemoryExtractor",
    "MemoryApplier",
    "MarkdownMemoryApplier",
    "LLMMemoryExtractor",
    "parse_memory_ops",
    "merge_global_core",
    "split_global_core",
    "MemoryStore",
    "MemoryScope",
    "MemoryFileMeta",
    "FileMemoryStore",
    "DocumentMemoryStore",
    "default_file_memory_store",
    "CORE_MEMORY_FILE",
    "PREFERENCES_MEMORY_FILE",
    "NAVIGATION_MEMORY_FILE",
    "ALWAYS_MEMORY_FILES",
    "TOPIC_DIR",
    "EPISODIC_DIR",
    "topic_path",
    "topic_slug",
    "is_topic_path",
    "episodic_path",
    "is_episodic_path",
    "default_memory_store",
    "memory_version",
    "maintain_user_memory",
    "MemoryUpdateItem",
    "EpisodeRecord",
    "clamp_summary",
    "should_run_semantic",
    "load_injected_memory",
    "load_memory_topics",
    "MemoryTopic",
    "RuleFragment",
    "assemble_injected_rules",
    "assemble_turn_rules",
    "compose_injected_rules",
    "append_user_rule",
    "append_user_rule_bullet",
]
