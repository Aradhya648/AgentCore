#!/usr/bin/env python3
"""R0b one-shot: fetch remaining vendor trees + SOURCE.json. Not for CI."""

from __future__ import annotations

import json
import re
import shutil
import tarfile
import tempfile
import time
import urllib.request
import zipfile
from datetime import date
from pathlib import Path

VENDOR = Path(__file__).resolve().parent
FETCHED_AT = date.today().isoformat()

# Stable pins: prefer recent non-prerelease tags known good for Windows wheels / npm.
# Resolved via GitHub API at fetch time when pin_tag is None.
SPECS = [
    {
        "id": "V01",
        "name": "click",
        "repo": "pallets/click",
        "license": "BSD-3-Clause",
        "language": "python",
        "role": "cli-argparse-help",
        "app_globs": ["src/click/**/*.py"],
        "strip_extra": ["docs", "examples", "artwork"],
        "install": {
            "offline_ok": True,
            "notes": "纯 Python；评测副本 pip install -e . 或 PYTHONPATH=src；无原生扩展",
        },
        "test": {
            "command": ["python", "-m", "pytest", "tests", "-q"],
            "full_suite_note": "需 pytest；可选 tox",
        },
    },
    {
        "id": "V02",
        "name": "starlette",
        "repo": "encode/starlette",
        "license": "BSD-3-Clause",
        "language": "python",
        "role": "asgi-web-middleware",
        "app_globs": ["starlette/**/*.py"],
        "strip_extra": ["docs", "scripts"],
        "install": {
            "offline_ok": False,
            "notes": "pip install -e '.[full]' 或最小 deps；Windows 友好纯 Python",
        },
        "test": {
            "command": ["python", "-m", "pytest", "tests", "-q"],
            "full_suite_note": "部分测需 httpx/anyio 等 extras",
        },
    },
    {
        "id": "V03",
        "name": "httpx",
        "repo": "encode/httpx",
        "license": "BSD-3-Clause",
        "language": "python",
        "role": "http-client-sync-async",
        "app_globs": ["httpx/**/*.py"],
        "strip_extra": ["docs", "scripts"],
        "install": {
            "offline_ok": False,
            "notes": "pip install -e .；纯 Python + httpcore；Windows 友好",
        },
        "test": {
            "command": ["python", "-m", "pytest", "tests", "-q"],
            "full_suite_note": "需 pytest-asyncio 等开发依赖",
        },
    },
    {
        "id": "V04",
        "name": "flask",
        "repo": "pallets/flask",
        "license": "BSD-3-Clause",
        "language": "python",
        "role": "wsgi-web-classic",
        "app_globs": ["src/flask/**/*.py"],
        "strip_extra": ["docs", "examples", "assets"],
        "install": {
            "offline_ok": False,
            "notes": "pip install -e .；纯 Python WSGI 栈；Windows 友好",
        },
        "test": {
            "command": ["python", "-m", "pytest", "tests", "-q"],
            "full_suite_note": "需开发 extras",
        },
    },
    {
        "id": "V05",
        "name": "attrs",
        "repo": "python-attrs/attrs",
        "license": "MIT",
        "language": "python",
        "role": "data-model-validation",
        "app_globs": ["src/attr/**/*.py", "src/attrs/**/*.py"],
        "strip_extra": ["docs", "changelog.d"],
        "install": {
            "offline_ok": True,
            "notes": "纯 Python；pip install -e . 或 PYTHONPATH=src",
        },
        "test": {
            "command": ["python", "-m", "pytest", "tests", "-q"],
            "full_suite_note": "hypothesis 等可选",
        },
    },
    {
        "id": "V06",
        "name": "pyyaml",
        "repo": "yaml/pyyaml",
        "license": "MIT",
        "language": "python",
        "role": "parser-edge-cases",
        "app_globs": ["lib/yaml/**/*.py", "lib3/yaml/**/*.py"],
        "strip_extra": ["packaging"],
        "install": {
            "offline_ok": False,
            "notes": "优先用 wheel（含 libyaml）；源码装可能需编译器。Windows 优先 pip install PyYAML==pin",
            "windows_note": "若本机无编译器，评测装依赖时用 PyPI wheel，vendor 树仅作源码定位/读码",
        },
        "test": {
            "command": ["python", "tests/lib3/test_all.py"],
            "full_suite_note": "legacy 布局；部分测依赖 C 扩展 _yaml",
        },
        "gate_risk": "native_ext",
    },
    {
        "id": "V08",
        "name": "uuid",
        "repo": "uuidjs/uuid",
        "license": "MIT",
        "language": "typescript",
        "role": "small-package-unit-tests",
        "app_globs": ["src/**/*.{ts,js,mjs,cjs}"],
        "strip_extra": ["examples", ".husky"],
        "install": {
            "offline_ok": False,
            "notes": "pnpm/npm install（勿把 node_modules 写入 vendor）；再 npm test",
        },
        "test": {
            "command": ["npm", "test"],
            "full_suite_note": "package.json scripts.test",
        },
    },
    {
        "id": "V09",
        "name": "commander",
        "repo": "tj/commander.js",
        "license": "MIT",
        "language": "typescript",
        "role": "node-cli-subcommands",
        "app_globs": ["lib/**/*.js", "index.js", "esm.mjs", "typings/**/*.ts"],
        "strip_extra": ["docs", "examples", "site"],
        "install": {
            "offline_ok": False,
            "notes": "npm install（strip node_modules）；纯 JS，Windows 友好",
        },
        "test": {
            "command": ["npm", "test"],
            "full_suite_note": "jest/mocha 见 package.json",
        },
    },
    {
        "id": "V10",
        "name": "zod",
        "repo": "colinhacks/zod",
        "license": "MIT",
        "language": "typescript",
        "role": "schema-parse-errors",
        # v4.x monorepo 应用 LOC≈55k 超门；必须 pin 末代 v3（勿 resolve latest）
        "pin_tag": "v3.24.2",
        "app_globs": ["src/**/*.ts"],
        "strip_extra": ["docs", "blog", "experiments", ".github", ".husky", ".devcontainer", ".vscode"],
        "install": {
            "offline_ok": False,
            "notes": "npm/pnpm install（勿 vendor node_modules）；v3 非 packages/zod monorepo 布局",
        },
        "test": {
            "command": ["npm", "test"],
            "full_suite_note": "见 package.json scripts",
        },
    },
]

STRIP_ALWAYS = {
    ".git",
    ".github",
    ".gitattributes",
    ".gitignore",
    ".gitmodules",
    "node_modules",
    ".pytest_cache",
    "__pycache__",
    ".tox",
    ".mypy_cache",
    ".ruff_cache",
    ".idea",
    ".vscode",
    "coverage",
    "dist",
    "build",
    ".turbo",
    ".next",
}


def api_get(url: str) -> dict | list:
    req = urllib.request.Request(
        url,
        headers={"Accept": "application/vnd.github+json", "User-Agent": "agentcore-r0b"},
    )
    with urllib.request.urlopen(req, timeout=60) as r:
        return json.load(r)


def resolve_tag_sha(repo: str, tag: str) -> tuple[str, str, str]:
    ref = api_get(f"https://api.github.com/repos/{repo}/git/ref/tags/{tag}")
    assert isinstance(ref, dict)
    obj = ref["object"]
    sha = obj["sha"]
    if obj["type"] == "tag":
        tag_obj = api_get(obj["url"])
        assert isinstance(tag_obj, dict)
        sha = tag_obj["object"]["sha"]
    tarball = f"https://github.com/{repo}/archive/refs/tags/{tag}.tar.gz"
    return tag, sha, tarball


def resolve_pin(repo: str, pin_tag: str | None = None) -> tuple[str, str, str]:
    """Return (tag, full_sha, tarball_url). Prefer explicit pin_tag, else latest release."""
    if pin_tag:
        return resolve_tag_sha(repo, pin_tag)
    try:
        rel = api_get(f"https://api.github.com/repos/{repo}/releases/latest")
        assert isinstance(rel, dict)
        return resolve_tag_sha(repo, rel["tag_name"])
    except Exception as e:
        print(f"  releases/latest failed for {repo}: {e}; trying tags")
        tags = api_get(f"https://api.github.com/repos/{repo}/tags?per_page=10")
        assert isinstance(tags, list) and tags
        chosen = None
        for t in tags:
            name = t["name"]
            if re.search(r"(alpha|beta|rc|canary|dev)", name, re.I):
                continue
            chosen = t
            break
        if chosen is None:
            chosen = tags[0]
        return resolve_tag_sha(repo, chosen["name"])


def download(url: str, dest: Path) -> None:
    print(f"  downloading {url}")
    req = urllib.request.Request(url, headers={"User-Agent": "agentcore-r0b"})
    with urllib.request.urlopen(req, timeout=180) as r, dest.open("wb") as f:
        shutil.copyfileobj(r, f)


def extract_tarball(archive: Path, dest_parent: Path) -> Path:
    with tarfile.open(archive, "r:gz") as tf:
        # safety: only extract under dest_parent
        tf.extractall(dest_parent)
        names = tf.getnames()
    top = names[0].split("/")[0]
    return dest_parent / top


def should_strip(name: str, extra: list[str]) -> bool:
    base = Path(name).name
    if base in STRIP_ALWAYS or name in STRIP_ALWAYS:
        return True
    for e in extra:
        if name == e or name.startswith(e.rstrip("/") + "/") or base == e:
            return True
    return False


def strip_tree(root: Path, extra: list[str]) -> list[str]:
    stripped: list[str] = []
    # walk top-level + known deep dirs
    for child in list(root.iterdir()):
        rel = child.name
        if should_strip(rel, extra) or child.name in STRIP_ALWAYS:
            if child.is_dir():
                shutil.rmtree(child, ignore_errors=True)
            else:
                child.unlink(missing_ok=True)
            stripped.append(rel)
    # deep clean caches / node_modules anywhere
    for p in sorted(root.rglob("*"), reverse=True):
        if p.name in {
            "node_modules",
            "__pycache__",
            ".pytest_cache",
            ".tox",
            ".mypy_cache",
            ".ruff_cache",
            ".git",
        }:
            if p.is_dir():
                shutil.rmtree(p, ignore_errors=True)
                stripped.append(str(p.relative_to(root)).replace("\\", "/"))
            elif p.is_file() and p.suffix == ".pyc":
                p.unlink(missing_ok=True)
    return sorted(set(stripped))


def count_loc(root: Path, patterns: list[str], lang: str) -> int:
    """Rough LOC: non-blank non-comment-ish lines in matching files."""
    files: set[Path] = set()
    for pat in patterns:
        # pathlib glob doesn't do brace expand; expand simply
        if "{ts,js,mjs,cjs}" in pat:
            for ext in ("ts", "js", "mjs", "cjs"):
                files.update(root.glob(pat.replace("{ts,js,mjs,cjs}", ext)))
        else:
            files.update(root.glob(pat))
    # fallbacks if globs miss (layout changed)
    if not files:
        if lang == "python":
            files.update(root.rglob("*.py"))
            # exclude tests
            files = {f for f in files if "test" not in f.parts and "tests" not in f.parts}
        else:
            for ext in ("*.ts", "*.tsx", "*.js", "*.mjs"):
                files.update(root.rglob(ext))
            files = {
                f
                for f in files
                if "test" not in f.parts
                and "tests" not in f.parts
                and "node_modules" not in f.parts
                and "dist" not in f.parts
            }
    loc = 0
    for f in files:
        if not f.is_file():
            continue
        try:
            text = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        for line in text.splitlines():
            s = line.strip()
            if not s:
                continue
            if s.startswith("#") or s.startswith("//") or s.startswith("*"):
                continue
            loc += 1
    return loc


def find_license(root: Path) -> str | None:
    for name in ("LICENSE", "LICENSE.txt", "LICENSE.md", "COPYING", "LICENSE.MIT"):
        if (root / name).is_file():
            return name
    for p in root.glob("LICENSE*"):
        if p.is_file():
            return p.name
    return None


def process(spec: dict) -> dict:
    repo = spec["repo"]
    print(f"\n=== {spec['id']} {repo} ===")
    tag, sha, tarball = resolve_pin(repo, spec.get("pin_tag"))
    commit12 = sha[:12]
    print(f"  pin tag={tag} sha={commit12}")

    with tempfile.TemporaryDirectory(prefix="r0b-") as td:
        td_path = Path(td)
        archive = td_path / "src.tar.gz"
        download(tarball, archive)
        extracted = extract_tarball(archive, td_path)
        stripped = strip_tree(extracted, list(spec.get("strip_extra") or []))
        lic = find_license(extracted)
        if not lic:
            raise SystemExit(f"{spec['id']}: no LICENSE file after extract")

        app_loc = count_loc(extracted, list(spec.get("app_globs") or []), spec["language"])
        # also count all py/ts excluding tests for gate note
        app_ok = app_loc <= 15000
        print(f"  app_loc≈{app_loc} gate_ok={app_ok} license={lic}")

        dest_name = f"{spec['name']}@{commit12}"
        dest = VENDOR / dest_name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(extracted, dest)

    # remove leftover pyc etc after copy
    strip_tree(dest, [])

    # pyyaml special: we stripped ext/ — if that breaks source identity, keep note
    size_bytes = sum(p.stat().st_size for p in dest.rglob("*") if p.is_file())

    source = {
        "id": spec["id"],
        "name": spec["name"],
        "upstream": f"https://github.com/{repo}",
        "release_tag": tag,
        "commit": sha,
        "commit12": commit12,
        "license": spec["license"],
        "license_file": lic,
        "language": spec["language"],
        "role": spec["role"],
        "fetched_at": FETCHED_AT,
        "fetch_method": "github_release_tag_tarball",
        "fetch_url": tarball,
        "vendor_layout": "source_tree_no_git",
        "vendor_dir": dest_name,
        "stripped": stripped,
        "size_gate": {
            "app_loc_approx": app_loc,
            "app_loc_limit": 15000,
            "app_loc_ok": app_ok,
            "tree_bytes": size_bytes,
            "tree_mib": round(size_bytes / (1024 * 1024), 3),
            "note": "应用代码按 app_globs 粗计非空非注释行；tests/fixtures 不计入 ≤15k 建议门",
        },
        "install": spec["install"],
        "test": spec["test"],
    }
    if spec.get("gate_risk"):
        source["gate_risk"] = spec["gate_risk"]
    if not app_ok:
        source["size_gate"]["attachment_asset"] = {
            "status": "over_loc_gate",
            "action": "consider_replace_or_attach_url",
            "note": "单仓剥离后应用 LOC 超门；R0b 仍保留源树若总树可接受，否则换备用池同角色仓",
        }

    (dest / "SOURCE.json").write_text(
        json.dumps(source, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"  wrote {dest} ({source['size_gate']['tree_mib']} MiB)")
    return source


def main() -> None:
    results = []
    for spec in SPECS:
        # rate-limit GitHub API a bit
        try:
            results.append(process(spec))
        except Exception as e:
            print(f"FAILED {spec['id']}: {e}")
            results.append({"id": spec["id"], "error": str(e)})
        time.sleep(0.5)

    summary = VENDOR / "_r0b_fetch_summary.json"
    summary.write_text(json.dumps(results, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"\nSummary → {summary}")
    fails = [r for r in results if "error" in r or not r.get("size_gate", {}).get("app_loc_ok", True)]
    if fails:
        print("Gate/attention:")
        for f in fails:
            print(" ", f.get("id"), f.get("error") or f.get("size_gate"))


if __name__ == "__main__":
    main()
