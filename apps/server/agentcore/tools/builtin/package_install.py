"""Cloud-controlled JS package install — network-layer registry allowlist (A) + cache (B).

- **A**：云端装包走 ``tools/sandbox/egress``（netns + allowlist proxy）；辅以 argv
  形态白名单 + 固定包装源 env + 拒绝改 registry 的 CLI 参数。无 chokepoint 时甲降级。
  本地（``backend.location=local``）不走主机 gVisor egress 门禁，只钉源 + 权限轴。
- **B**：云端 ``install_cache_env`` → 沙箱 ``/pkg-cache``（OCI bind 到
  ``DATA_DIR/pkg-cache/<bucket>``）。云端 install 将持久工作区 rw-bind 到
  ``/workspace``，``node_modules`` 直接落盘（短命沙箱只跑命令，不整树 base64 回传）。

Used by ``test_run`` (check=install / command=npm|pnpm|yarn install|ci).
"""

from __future__ import annotations

import re
from pathlib import PurePosixPath

# In-sandbox mount for package-manager caches (must match egress.PACKAGE_CACHE_MOUNT).
_PACKAGE_CACHE_MOUNT = "/pkg-cache"

# Official npm registry + common CN mirror. Pin via env; CLI overrides rejected.
ALLOWED_NPM_REGISTRIES: tuple[str, ...] = (
    "https://registry.npmjs.org/",
    "https://registry.npmmirror.com/",
)
DEFAULT_NPM_REGISTRY = ALLOWED_NPM_REGISTRIES[0]

# Egress-only packaging CDN hosts (unioned by egress/hosts.py). CDN ≠ 可改 registry：
# 仅出网放行 tarball/二进制拉取，勿当作可 pin / --registry 的包装源 URL。
# npm 官方 tarball 仍在 registry.npmjs.org（无独立 CDN 主机名），故不另列。
ALLOWED_NPM_HOSTS: tuple[str, ...] = (
    "cdn.npmmirror.com",
)

# Install / ci budget uses the same gVisor ceiling as other verify checks.
# Exposed so callers can document "aligned to sandbox max" without a second 60s trap.
INSTALL_NEEDS_RESTRICTED_NETWORK = True

_INSTALL_VERBS = frozenset({"install", "ci", "i", "add"})
_PM_BINS = frozenset({"npm", "pnpm", "yarn"})

# Flags that re-point the package source away from the pinned allowlist.
_REGISTRY_OVERRIDE_FLAGS = frozenset(
    {
        "--registry",
        "--reg",
        "--npm-registry",
        "--npmregistryserver",
    }
)

_REGISTRY_OVERRIDE_RE = re.compile(
    r"^(?:"
    r"--registry=.+"
    r"|--reg=.+"
    r"|--npm-registry=.+"
    r"|--npmRegistryServer=.+"
    r"|npmRegistryServer=.+"
    r"|registry=.+"
    r"|--@[A-Za-z0-9~._-]+:registry=.+"
    r")$",
    re.IGNORECASE,
)

_SHELL_CHAIN_HINT_RE = re.compile(
    r"(?:&&|\|\||;|`|\$\(|^\s*(?:cd|pushd)\b)",
    re.IGNORECASE,
)

_NETWORK_DEGRADE_CODE = "install_network_unavailable"


def is_install_shaped_argv(argv: list[str]) -> bool:
    """True for ``npm|pnpm|yarn (install|ci|i|add)`` after optional safe dir flags."""
    pm, rest = _split_pm_and_rest(argv)
    if pm is None or not rest:
        return False
    return rest[0].lower() in _INSTALL_VERBS


def install_prefix_allowed(argv: list[str]) -> bool:
    """Prefix match for ``_ALLOWED_PREFIXES``-style checks (pm + verb)."""
    pm, rest = _split_pm_and_rest(argv)
    if pm is None or not rest:
        return False
    return rest[0].lower() in _INSTALL_VERBS


def _split_pm_and_rest(argv: list[str]) -> tuple[str | None, list[str]]:
    """Return (pm, argv_after_optional_dir_flags) or (None, [])."""
    if not argv:
        return None, []
    head = argv[0].lower()
    if head not in _PM_BINS:
        return None, []
    i = 1
    # Safe subdirectory flags before the verb: --prefix/--dir/-C/--cwd <rel>
    while i < len(argv):
        flag = argv[i]
        flag_l = flag.lower()
        if flag_l in ("--prefix", "--dir", "-c", "--cwd") and i + 1 < len(argv):
            if not is_safe_relpath(argv[i + 1]):
                return None, []
            i += 2
            continue
        if flag_l.startswith("--prefix=") or flag_l.startswith("--dir="):
            _, _, val = flag.partition("=")
            if not is_safe_relpath(val):
                return None, []
            i += 1
            continue
        break
    return head, argv[i:]


def is_safe_relpath(raw: str) -> bool:
    """Workspace-relative path only: no abs, no ``..``, no empty / drive letters."""
    text = (raw or "").strip().replace("\\", "/")
    if not text or text.startswith("/") or text.startswith("~"):
        return False
    if re.match(r"^[A-Za-z]:", text):
        return False
    # PurePosixPath(".").parts is () on some platforms — treat as workspace root.
    if text in (".", "./"):
        return True
    parts = PurePosixPath(text).parts
    return bool(parts) and ".." not in parts


def reject_shell_chain_command(command: str) -> str | None:
    """Refuse ``cd && npm install`` / shell metacharacters in the raw command string."""
    text = (command or "").strip()
    if not text:
        return None
    if _SHELL_CHAIN_HINT_RE.search(text):
        return (
            "禁止用 shell 链（cd && / ; / ||）跑装包；"
            "请用 test_run check=install（可选 working_directory），"
            "或 check=command + `npm|pnpm|yarn install`，"
            "子目录用 --prefix / --dir / working_directory（相对路径）。"
        )
    return None


def reject_registry_override_argv(argv: list[str]) -> str | None:
    """Refuse CLI args that change the package registry (首版控制面)."""
    i = 0
    while i < len(argv):
        arg = argv[i]
        low = arg.lower()
        if low in _REGISTRY_OVERRIDE_FLAGS:
            return (
                f"禁止改包装源（检测到 {arg}）。"
                f"云端装包固定 allowlist registry（"
                f"{', '.join(ALLOWED_NPM_REGISTRIES)}）；"
                "勿传 --registry / scope:registry。"
            )
        if _REGISTRY_OVERRIDE_RE.match(arg):
            return (
                f"禁止改包装源（检测到 {arg}）。"
                f"云端装包固定 allowlist registry；"
                "勿传 --registry / scope:registry。"
            )
        i += 1
    return None


def validate_install_argv(argv: list[str]) -> str | None:
    """Return error message if install argv is unsafe; None if ok."""
    if not install_prefix_allowed(argv):
        return f"不是允许的装包形态：{' '.join(argv)}"
    reg_err = reject_registry_override_argv(argv)
    if reg_err:
        return reg_err
    # Re-validate any --prefix/--dir values (also done in split)
    i = 0
    while i < len(argv):
        low = argv[i].lower()
        if low in ("--prefix", "--dir", "-c", "--cwd") and i + 1 < len(argv):
            if not is_safe_relpath(argv[i + 1]):
                return (
                    f"装包子目录必须是工作区相对安全路径（禁止绝对路径 / ..）：{argv[i + 1]}"
                )
            i += 2
            continue
        if low.startswith("--prefix=") or low.startswith("--dir="):
            _, _, val = argv[i].partition("=")
            if not is_safe_relpath(val):
                return f"装包子目录必须是工作区相对安全路径：{val}"
        i += 1
    return None


def registry_pin_env() -> dict[str, str]:
    """Env that pins common package managers to the default allowlisted registry.

    Complements the network-layer allowlist proxy (egress); argv overrides still rejected.
    """
    reg = DEFAULT_NPM_REGISTRY
    return {
        "NPM_CONFIG_REGISTRY": reg,
        "npm_config_registry": reg,
        "YARN_NPM_REGISTRY_SERVER": reg,
        "YARN_REGISTRY": reg,
        # pnpm reads npm_config_registry / NPM_CONFIG_REGISTRY
        "PNPM_REGISTRY": reg,
    }


def install_cache_env() -> dict[str, str]:
    """B 预缓存：指向沙箱内 ``/pkg-cache``（OCI bind 到 DATA_DIR 分桶目录）。"""
    root = _PACKAGE_CACHE_MOUNT
    return {
        "NPM_CONFIG_CACHE": f"{root}/npm",
        "npm_config_cache": f"{root}/npm",
        "YARN_CACHE_FOLDER": f"{root}/yarn",
        "PNPM_STORE_PATH": f"{root}/pnpm",
    }


def network_unavailable_message() -> str:
    """甲降级：无法装包时的诚实说明（勿空转跑 install）。"""
    return (
        "无法装包：当前会话未授权受限出网，或云端主机不具备包装源白名单出网能力"
        "（云端需 Linux gVisor + netns chokepoint；本机执行不依赖主机 gVisor）。"
        "装包不会在无授权 / 无 chokepoint 时空转。\n"
        "可选降级：① 将命令执行轴设为 auto 后重试 test_run check=install "
        "→ build；② 走结构自检（graph_consistent / import 图）；"
        "③ 本地绑定工作区后在本机 npm/pnpm/yarn install，或 export_to_local。"
    )


def network_unavailable_code() -> str:
    return _NETWORK_DEGRADE_CODE


def resolve_install_argv(
    *,
    package_managers: list[str],
    working_directory: str | None = None,
) -> list[str]:
    """Build default ``<pm> install`` argv from workspace profile."""
    pm = "npm"
    for candidate in ("pnpm", "yarn", "npm"):
        if candidate in package_managers:
            pm = candidate
            break
    argv = [pm, "install"]
    wd = (working_directory or "").strip()
    if wd:
        if pm == "npm":
            argv = ["npm", "--prefix", wd, "install"]
        elif pm == "pnpm":
            argv = ["pnpm", "--dir", wd, "install"]
        else:
            argv = ["yarn", "--cwd", wd, "install"]
    return argv


def apply_working_directory(argv: list[str], working_directory: str | None) -> list[str]:
    """Inject safe subdirectory flags when tool param is set and argv lacks one."""
    wd = (working_directory or "").strip()
    if not wd:
        return argv
    if not argv:
        return argv
    pm = argv[0].lower()
    if pm not in _PM_BINS:
        return argv
    # Already has a dir flag
    for a in argv[1:]:
        low = a.lower()
        if low in ("--prefix", "--dir", "-c", "--cwd") or low.startswith(
            ("--prefix=", "--dir=")
        ):
            return argv
    if pm == "npm":
        return ["npm", "--prefix", wd, *argv[1:]]
    if pm == "pnpm":
        return ["pnpm", "--dir", wd, *argv[1:]]
    return ["yarn", "--cwd", wd, *argv[1:]]
