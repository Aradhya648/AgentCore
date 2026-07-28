"""Unit tests for workspace project profile detection (no DB)."""

from textwrap import dedent

from agentcore.runtime.context.workspace_profile import (
    _PROFILE_MAX_COMMANDS,
    WorkspaceProfile,
    detect_workspace_profile,
    render_workspace_profile,
)


class _FakeBackend:
    """Minimal WorkspaceBackend stand-in with fixture file contents."""

    def __init__(self, files: dict[str, str]) -> None:
        self._files = files

    async def read(self, path: str) -> str:
        if path not in self._files:
            raise FileNotFoundError(path)
        return self._files[path]


async def test_detects_npm_start_and_dev_scripts():
    backend = _FakeBackend(
        {
            "package.json": """{
  "name": "demo",
  "scripts": {
    "start": "node index.js",
    "dev": "vite",
    "test": "vitest"
  }
}"""
        }
    )
    profile = await detect_workspace_profile(backend)
    assert profile.run_commands == ["npm run start", "npm run dev"]
    assert "npm" in profile.package_managers


async def test_detects_pnpm_run_commands():
    backend = _FakeBackend(
        {
            "package.json": """{
  "name": "demo",
  "packageManager": "pnpm@9.0.0",
  "scripts": {
    "start": "node index.js",
    "dev": "vite dev"
  }
}"""
        }
    )
    profile = await detect_workspace_profile(backend)
    assert profile.run_commands == ["pnpm run start", "pnpm run dev"]
    assert "pnpm" in profile.package_managers


async def test_detects_yarn_run_commands():
    backend = _FakeBackend(
        {
            "package.json": """{
  "name": "demo",
  "packageManager": "yarn@4.0.0",
  "scripts": {
    "dev": "next dev"
  }
}"""
        }
    )
    profile = await detect_workspace_profile(backend)
    assert profile.run_commands == ["yarn dev"]
    assert "yarn" in profile.package_managers


async def test_detects_uv_console_script_from_pyproject():
    backend = _FakeBackend(
        {
            "pyproject.toml": dedent(
                """\
                [project]
                name = "agentcore"

                [project.scripts]
                agentcore = "agentcore.__main__:main"

                [tool.uv]
                """
            ),
        }
    )
    profile = await detect_workspace_profile(backend)
    assert profile.run_commands == ["uv run agentcore"]
    assert "uv" in profile.package_managers


async def test_detects_pip_console_script_from_pyproject():
    backend = _FakeBackend(
        {
            "pyproject.toml": dedent(
                """\
                [project]
                name = "demo"

                [project.scripts]
                demo-cli = "demo.cli:main"
                """
            ),
        }
    )
    profile = await detect_workspace_profile(backend)
    assert profile.run_commands == ["pip run demo-cli"]
    assert "pip" in profile.package_managers


async def test_detects_typecheck_from_package_and_tsconfig():
    backend = _FakeBackend(
        {
            "package.json": """{
  "name": "demo",
  "scripts": {
    "typecheck": "tsc --noEmit",
    "build": "vite build"
  }
}""",
            "tsconfig.json": "{}",
        }
    )
    profile = await detect_workspace_profile(backend)
    assert any("typecheck" in c for c in profile.typecheck_commands)
    assert any("build" in c for c in profile.build_commands)


async def test_render_includes_run_commands_under_common_commands():
    profile = WorkspaceProfile(
        languages=["javascript"],
        test_commands=["npm test"],
        build_commands=["npm run build"],
        run_commands=["npm run start", "npm run dev"],
    )
    rendered = render_workspace_profile(profile)
    assert "常用命令：" in rendered
    assert "npm test" in rendered
    assert "npm run build" in rendered
    assert "npm run start" in rendered
    assert "npm run dev" in rendered


def test_render_caps_total_commands_shown():
    profile = WorkspaceProfile(
        languages=["python"],
        test_commands=["pytest", "npm test"],
        build_commands=["npm run build"],
        run_commands=["npm run start", "npm run dev", "uv run app"],
    )
    rendered = render_workspace_profile(profile)
    command_line = next(line for line in rendered.splitlines() if "常用命令：" in line)
    shown = command_line.removeprefix("- 常用命令：").split(" · ")
    assert len(shown) == _PROFILE_MAX_COMMANDS
