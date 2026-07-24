"""Sidecar import-boundary guard — desktop local engine depends on a clean import graph."""

from __future__ import annotations

import importlib


def test_sidecar_package_imports_without_cycle() -> None:
    """Desktop spawns ``python -m agentcore.sidecar`` — import graph must stay acyclic."""
    importlib.import_module("agentcore.sidecar.server_pkg")
    importlib.import_module("agentcore.sidecar.server")
