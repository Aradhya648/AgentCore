"""Platform LLM upstream, vendor keys, vision, and billing settings."""

from __future__ import annotations

import json

from pydantic import BaseModel


class PlatformSettings(BaseModel):
    platform_api_key: str = ""
    platform_base_url: str = "https://api.deepseek.com"
    platform_model: str = "deepseek-v4-flash"
    # Background purposes (title/memory/compaction/followups); empty = follow platform_model.
    platform_background_model: str = ""
    # Explicit platform model catalog allowlist (运营配置, 成本配额与计费 §〇·六 F3):
    # comma-separated ids the operator subsidizes on the partner relay. Empty = fall
    # back to platform_model (+ background) so byok / free-tier deployments are
    # unchanged. Every listed id MUST have a curated price card (F4); discovery of the
    # full upstream set is deliberately NOT used here (stays a BYOK-row concern).
    platform_models: str = ""
    # Per-model platform credential overrides (运营中转「一 key 一模型」, 成本配额与计费
    # §〇·六 F3): a JSON object mapping model id → {"api_key"?, "base_url"?}. When a model
    # in the catalog has an entry, its api_key / base_url win for that model; each missing
    # field falls back to platform_api_key / platform_base_url. Empty = every platform
    # model shares the default key/base_url (byok / free-tier deployments unchanged).
    platform_model_credentials: str = ""

    # --- 多厂商 provider（OpenAI 兼容，经 ProviderRouter 按 provider/model 前缀路由） ---
    moonshot_api_key: str = ""
    moonshot_base_url: str = "https://api.moonshot.cn/v1"
    zhipu_api_key: str = ""
    zhipu_base_url: str = "https://open.bigmodel.cn/api/paas/v4"
    doubao_api_key: str = ""
    doubao_base_url: str = "https://ark.cn-beijing.volces.com/api/v3"

    # --- AI 协作白板 读图 ---
    vision_api_key: str = ""
    vision_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    vision_model: str = "qwen-vl-max"
    vision_timeout_seconds: float = 60.0

    # --- 计费模式 ---
    billing_mode: str = "byok"
    # BYOK 部署下：无用户 key 时是否允许 fallback 到平台代付免费档（默认关）。
    platform_free_tier_enabled: bool = False

    # Sub2API 管理 API（可选）。配置后 platform 模式 503 时自动探测账号状态生成诊断。
    sub2api_admin_url: str = ""
    sub2api_admin_email: str = ""
    sub2api_admin_password: str = ""

    # AES-256-GCM 主密钥，用于把 BYOK API Key 加密后落库。
    encryption_key: str = ""


def parse_platform_model_credentials(raw: str) -> dict[str, dict[str, str]]:
    """Parse ``PLATFORM_MODEL_CREDENTIALS`` JSON into ``{model_id: {api_key?, base_url?}}``.

    Malformed JSON / wrong shape degrades to ``{}`` (logged) so an operator typo never
    crashes a turn — the platform then serves every model on the shared default key.
    Only non-blank ``api_key`` / ``base_url`` fields are kept, so an empty entry drops out.
    """
    text = (raw or "").strip()
    if not text:
        return {}
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, ValueError) as e:
        from agentcore.core.logging import get_logger

        get_logger(__name__).warning("platform.model_credentials_parse_failed", error=str(e))
        return {}
    if not isinstance(data, dict):
        from agentcore.core.logging import get_logger

        get_logger(__name__).warning("platform.model_credentials_not_object")
        return {}
    result: dict[str, dict[str, str]] = {}
    for model_id, entry in data.items():
        mid = str(model_id).strip()
        if not mid or not isinstance(entry, dict):
            continue
        creds: dict[str, str] = {}
        api_key = str(entry.get("api_key", "") or "").strip()
        base_url = str(entry.get("base_url", "") or "").strip()
        if api_key:
            creds["api_key"] = api_key
        if base_url:
            creds["base_url"] = base_url
        if creds:
            result[mid] = creds
    return result
