"""Turn persistence: roster, memory consolidation, compaction."""

from pydantic import BaseModel


class PersistenceSettings(BaseModel):
    incomplete_turn_persist_enabled: bool = True

    session_roster_persist_enabled: bool = True
    # 现场保留语义「对话在，现场就在」（同人连续委派，2026-07-12 拍板）：删对话级联清理是
    # 唯一默认清理路径；按时长清扫默认关（0 = 不清），>0 仅作放量后的存储保护兜底。
    session_roster_retention_days: int = 0
    session_roster_sweep_interval_seconds: int = 6 * 3600
    session_roster_sweep_batch_limit: int = 200

    audit_retention_days: int = 90
    audit_retention_sweep_interval_seconds: int = 24 * 3600
    audit_retention_sweep_batch_limit: int = 500

    memory_consolidation_enabled: bool = True
    # Episodic layer: idle debounce / turn-cap still trigger a per-conversation session
    # summary write (not a direct semantic write). Names kept for existing env overrides.
    memory_consolidation_idle_seconds: float = 90.0
    memory_consolidation_turn_cap: int = 8
    memory_consolidation_window_messages: int = 40
    memory_consolidation_sweep_interval_seconds: int = 300
    memory_consolidation_sweep_batch_limit: int = 100
    # Episodic session summary hard cap (chars); LLM output is truncated to this.
    memory_episodic_summary_max_chars: int = 200
    # Semantic consolidation triggers (either condition): undigested episodic count, or
    # hours since the last successful semantic pass for that (user, scope).
    memory_semantic_min_episodes: int = 3
    memory_semantic_max_age_hours: float = 24.0
    memory_section_bullet_cap: int = 20
    # Max on-demand topic notes (主题/<slug>.md) per user; new ones beyond this are
    # dropped by the consolidation pass (anti-bloat backstop, 记忆文件夹化 §七).
    memory_max_topic_files: int = 24
    # R1 fingerprint-dirty explore refresh (旁路): per-folder debounce; never blocks the turn.
    memory_explore_refresh_enabled: bool = True
    memory_explore_refresh_idle_seconds: float = 45.0
    # Read-side backstop to the write-side ``memory_section_bullet_cap`` (项目审计-成本性能
    # 专项 COST-001): each always-injected memory file (偏好.md / 画像.md / 项目画像) is
    # DETERMINISTICALLY capped to this many chars before it rides the turn's <rules>. Memory
    # sits in the stable prefix (SectionOrder.MEMORY) so the cap MUST be deterministic — same
    # body → same truncation → prefix stays byte-stable for DeepSeek's cache. Generous: only
    # fires on abnormal bloat (a normal 偏好/画像 is far smaller). 0/negative = no cap.
    memory_injected_file_char_cap: int = 4_000

    # Document 子系统第一期 (Agent记忆与知识系统 §5.7). Cross-file rule injection budget: the
    # ``<rules>`` block admits at most this many always-injected rule docs (user rules + AI
    # memory core), totalling at most this many chars, with GLOBAL surviving first when tight
    # (兑现 §5.3「全局优先存活」, replaces the per-file memory cap 单轨). Generous — normal memory
    # is far under, so it only trims abnormal bloat.
    max_instruction_docs: int = 32
    max_instruction_chars: int = 24_000
    # One-time file→document memory migration (§5.7 换底): copy file-backed memory into the
    # documents tree at startup. Idempotent + best-effort; safe to leave on (a no-op once done).
    memory_documents_migration_enabled: bool = True

    compaction_enabled: bool = True
    compaction_trigger_input_tokens: int = 64_000
    compaction_recency_messages: int = 20
    compaction_min_fold_messages: int = 4
    compaction_max_fold_messages: int = 200
    compaction_context_max_messages: int = 300
    compaction_summary_char_budget: int = 4_000

    # Standing tasks / 定时自动化 L1: in-process DB poll of next_run_at + lease.
    standing_task_scheduler_enabled: bool = True
    standing_task_poll_interval_seconds: int = 30
    standing_task_poll_batch_limit: int = 10
    standing_task_lease_seconds: int = 30 * 60
    # L2a webhook: per-task sliding window + optional idempotency key TTL.
    standing_task_webhook_rate_limit_max: int = 30
    standing_task_webhook_rate_limit_window_seconds: int = 60
    standing_task_webhook_idempotency_ttl_seconds: int = 3600

    # Assembled system-prompt budget (项目审计-成本性能专项 COST-004). Observe-only today:
    # ``cost.prompt_assembled`` logs per-section chars + whether the turn's CEO system prompt
    # exceeds this soft cap, to gather data (无真实数据期 → 先观测, 后开「仅裁易变尾」软闸).
    # ~120k chars ≈ 数万 token, far below DeepSeek's 1M window but enough to flag abnormal bloat.
    prompt_budget_char_soft_cap: int = 120_000
