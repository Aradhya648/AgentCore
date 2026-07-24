"""HTTP server, logging, build provenance, desktop updates, push."""

from typing import Self

from pydantic import BaseModel, model_validator


class ServerSettings(BaseModel):
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    # None = follow debug (WatchFiles on when DEBUG=true). Explicit false keeps
    # DEBUG=true (dev logs / auto-migrate) but disables uvicorn hot-reload for
    # long live collaboration runs. Env: AGENTCORE_RELOAD.
    agentcore_reload: bool | None = None

    log_level: str = "info"
    log_file: str = ""
    log_llm_bodies: bool = False

    git_sha: str = "unknown"
    built_at: str = "unknown"

    desktop_updates_enabled: bool = True
    # Soft floor for desktop clients (GET /updates/policy → min_desktop_version).
    # Empty = no outdated banner (dev-friendly). Production often sets e.g. 0.6.5.
    desktop_min_version: str = ""

    push_enabled: bool = False
    fcm_project_id: str = ""
    fcm_service_account_path: str = ""

    @model_validator(mode="after")
    def _default_dev_log_file(self) -> Self:
        """Dev writes queryable JSONL without requiring LOG_FILE in .env."""
        if self.debug and not self.log_file:
            self.log_file = "logs/dev.jsonl"
        return self
