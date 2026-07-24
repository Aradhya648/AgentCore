"""Console entry point for running the AgentCore API server.

Usage:
    uv run agentcore           # via the project script
    uv run python -m agentcore

Host / port / reload are read from Settings (.env) so that manual runs match the
VS Code auto-start task instead of hardcoding the same flags in two places.

Build provenance (GIT_SHA / BUILT_AT) is resolved here — before Settings is
imported — so a manual run and the systemd ExecStart share one stamping seam and
every uvicorn reload worker inherits the values (children inherit the parent
environment). The release pipeline may inject them via the environment, which
always takes precedence.
"""

from agentcore.buildinfo import resolve_build_provenance


def main() -> None:
    # Must precede the Settings import so the stamped values reach config and,
    # in reload mode, every worker process that re-reads the environment.
    resolve_build_provenance()

    import multiprocessing

    import uvicorn

    from agentcore.config import settings
    from agentcore.startup_port import ensure_port_available

    # Demo-tape record/replay holds multi-minute SSE (原速 ~20min). WatchFiles +
    # timeout_graceful_shutdown=2 hard-kills that stream on any agentcore/ save →
    # process exit_code=1, no Traceback, desktop "无法连接后端". Demo modes win.
    demo_tape_busy = (
        settings.demo_tape_record_enabled or settings.demo_tape_replay_enabled
    )
    # AGENTCORE_RELOAD=false: keep DEBUG=true (console logs / auto-migrate) but
    # disable WatchFiles so long live runs survive agentcore/ saves. None = legacy
    # (reload follows debug). Demo-tape still forces reload off.
    if settings.agentcore_reload is None:
        reload = settings.debug and not demo_tape_busy
    else:
        reload = bool(settings.agentcore_reload) and not demo_tape_busy
    if not reload and settings.debug:
        reasons: list[str] = []
        if settings.agentcore_reload is False:
            reasons.append("AGENTCORE_RELOAD=false")
        if settings.demo_tape_record_enabled:
            reasons.append("DEMO_TAPE_RECORD_ENABLED")
        if settings.demo_tape_replay_enabled:
            reasons.append("DEMO_TAPE_REPLAY_ENABLED")
        if reasons:
            print(
                "WatchFiles reload disabled ("
                + " + ".join(reasons)
                + "): long SSE would be killed by "
                "timeout_graceful_shutdown=2. Restart the backend after code changes.",
                flush=True,
            )

    # Only the true launcher process probes. Uvicorn reload workers are spawn
    # children that must not fail-fast against the socket the reloader already
    # bound (and must not print a false "another instance" error).
    if multiprocessing.current_process().name == "MainProcess":
        ensure_port_available(settings.host, settings.port)

    uvicorn.run(
        "agentcore.main:app",
        host=settings.host,
        port=settings.port,
        # Hot-reload: DEBUG + AGENTCORE_RELOAD (unless demo tape is armed — see above).
        reload=reload,
        # Watch only the app package, not the whole cwd: apps/server also holds
        # test artifacts (.pytmp/.pytest_*) full of .py fixtures whose churn would
        # otherwise trigger endless reloads. (Ignored when reload is off.)
        reload_dirs=["agentcore"],
        # Batch rapid saves (parallel agents touching agentcore/) into one reload so
        # the reloader doesn't churn through shutdown/start cycles that can leave
        # port 8000 empty while the terminal still looks "running".
        reload_delay=0.5 if reload else None,
        # In dev, reload must not block forever draining the long-lived SSE stream
        # ("Waiting for connections to close" → no new worker → API dead). Cap the
        # graceful wait so a save force-closes lingering streams and the worker
        # restarts; the desktop EventSource reconnects. Prod / demo-tape (reload
        # off) keep the default (None).
        timeout_graceful_shutdown=2 if reload else None,
    )


if __name__ == "__main__":
    main()
