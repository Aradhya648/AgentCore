"""Unit tests for cloud-controlled package install allowlist (package_install)."""

from __future__ import annotations

import pytest

from agentcore.tools.builtin.package_install import (
    apply_working_directory,
    install_prefix_allowed,
    is_install_shaped_argv,
    is_safe_relpath,
    registry_pin_env,
    reject_registry_override_argv,
    reject_shell_chain_command,
    resolve_install_argv,
    validate_install_argv,
)


@pytest.mark.parametrize(
    "argv",
    [
        ["npm", "install"],
        ["npm", "ci"],
        ["pnpm", "install", "--frozen-lockfile"],
        ["yarn", "install"],
        ["npm", "--prefix", "apps/web", "install"],
        ["pnpm", "--dir", "pkg", "ci"],
        ["yarn", "--cwd", "frontend", "install"],
    ],
)
def test_install_shaped_accepted(argv: list[str]):
    assert is_install_shaped_argv(argv) is True
    assert install_prefix_allowed(argv) is True
    assert validate_install_argv(argv) is None


@pytest.mark.parametrize(
    "argv",
    [
        ["npm", "run", "build"],
        ["npm", "test"],
        ["bash", "-c", "npm install"],
        ["npm", "--prefix", "../x", "install"],
    ],
)
def test_install_shaped_rejected(argv: list[str]):
    assert validate_install_argv(argv) is not None or not install_prefix_allowed(argv)


def test_reject_shell_chain():
    assert reject_shell_chain_command("cd foo && npm install") is not None
    assert reject_shell_chain_command("npm install") is None


def test_reject_registry_override():
    err = reject_registry_override_argv(
        ["npm", "install", "--registry", "https://evil.example/"]
    )
    assert err is not None
    assert "包装源" in err
    assert (
        reject_registry_override_argv(["npm", "install", "--registry=https://evil/"])
        is not None
    )
    assert reject_registry_override_argv(["npm", "install"]) is None


def test_safe_relpath():
    assert is_safe_relpath("apps/web") is True
    assert is_safe_relpath(".") is True
    assert is_safe_relpath("../x") is False
    assert is_safe_relpath("/etc") is False
    assert is_safe_relpath("C:\\Windows") is False


def test_resolve_and_apply_working_directory():
    assert resolve_install_argv(package_managers=["pnpm"]) == ["pnpm", "install"]
    assert resolve_install_argv(
        package_managers=["npm"], working_directory="apps/web"
    ) == ["npm", "--prefix", "apps/web", "install"]
    assert apply_working_directory(["npm", "install"], "apps/web") == [
        "npm",
        "--prefix",
        "apps/web",
        "install",
    ]


def test_registry_pin_env_points_at_allowlist():
    env = registry_pin_env()
    assert "registry.npmjs.org" in env["NPM_CONFIG_REGISTRY"]


def test_install_cache_env_points_at_pkg_cache():
    from agentcore.tools.builtin.package_install import install_cache_env

    env = install_cache_env()
    assert env["NPM_CONFIG_CACHE"] == "/pkg-cache/npm"
    assert env["PNPM_STORE_PATH"] == "/pkg-cache/pnpm"
