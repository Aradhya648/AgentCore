"""Sidecar — host the SAME runtime engine in a process on the user's machine.

This package is the local-engine half of 双模式工作区 / 远期规划 §一.1 (Sidecar
可迁移核): the desktop spawns ``python -m agentcore.sidecar`` and drives it over
stdio JSON-RPC, so a turn runs entirely on the user's machine (files + code touch
the real local disk directly — no ``WorkspaceChannel`` round-trip per op).

The engine itself is reused verbatim (``runtime.pipeline.run_chat_pipeline``);
only the §8.6 host ports are swapped for local implementations:

- **EventSink** → the turn's events are pumped out as ``turn/event`` JSON-RPC
  notifications instead of an SSE stream (``sidecar.server``).
- **Workspace** → a plain ``ServerWorkspace`` rooted at the bound local directory
  (the sidecar runs ON the machine, so it touches ``Path`` directly).
- **InferenceGateway** → DeepSeek reached through the cloud proxy (the platform
  key is never placed on the user's machine), wired via the per-turn
  ``LLMCredentials`` the engine already injects into ``build_provider``.

Persistence is progressive **OutboxStore** on disk (as-built: 双模式工作区 §10.3):
begin / checkpoint / journal / finalize land under ``<dataDir>/outbox/``; the
Electron main-process writebacker drains ready records via Bearer
``POST .../local-turns`` → ``CloudStore.finalize(mode="local")``. Spend is metered
authoritatively at the cloud inference proxy (Slice 4a), not relayed from the
client. Packaging is handled too: a packaged
desktop ships a standalone CPython + ``--target`` site-packages and spawns it when
``app.isPackaged`` (no system Python/venv/uv needed — see
``apps/desktop/scripts/bundle-sidecar.mjs``). Still deferred: offline LLM. See
``docs/06-规划/远期规划.md §一``.
"""
