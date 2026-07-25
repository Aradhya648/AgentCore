"""Download and verify a pinned ripgrep binary (build / local / desktop).

Mirrors ``fetch_runsc.py``: stdlib only, env-overridable URL + digest.

Default pin: ripgrep 14.1.1 from GitHub Releases. Targets:

- Linux Docker / amd64: ``x86_64-unknown-linux-musl`` (static)
- Windows: ``x86_64-pc-windows-msvc``
- macOS arm64: ``aarch64-apple-darwin``
- macOS x86_64: ``x86_64-apple-darwin``
- Linux arm64: ``aarch64-unknown-linux-gnu``

Usage::

    python fetch_ripgrep.py /out/rg
    python fetch_ripgrep.py --install-server   # → apps/server/bin/rg[.exe]
    python fetch_ripgrep.py --install-desktop  # → apps/desktop/resources/rg/rg[.exe]

Env:

- ``RG_VERSION`` (default ``14.1.1``)
- ``RG_TARGET`` (override triple; empty → auto-detect host / linux-musl in Docker)
- ``RG_URL`` (full archive URL; empty → GitHub release asset)
- ``RG_SHA256`` (expected digest; empty → fetch ``${archive}.sha256``;
  literal ``skip`` → no verification)
"""

from __future__ import annotations

import argparse
import hashlib
import os
import platform
import shutil
import subprocess
import tarfile
import tempfile
import urllib.request
import zipfile
from pathlib import Path

_DEFAULT_VERSION = "14.1.1"
_GITHUB = "https://github.com/BurntSushi/ripgrep/releases/download"
# Mainland / flaky-GitHub build hosts: try official first, then common proxies.
_GITHUB_MIRROR_PREFIXES = (
    "https://ghfast.top/",
    "https://ghproxy.net/",
    "https://mirror.ghproxy.com/",
)


def _host_target() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if system == "windows":
        return "x86_64-pc-windows-msvc"
    if system == "darwin":
        if machine in ("arm64", "aarch64"):
            return "aarch64-apple-darwin"
        return "x86_64-apple-darwin"
    if system == "linux":
        if machine in ("arm64", "aarch64"):
            return "aarch64-unknown-linux-gnu"
        return "x86_64-unknown-linux-musl"
    raise SystemExit(f"unsupported platform for ripgrep fetch: {system}/{machine}")


def _archive_name(version: str, target: str) -> str:
    if "windows" in target:
        return f"ripgrep-{version}-{target}.zip"
    return f"ripgrep-{version}-{target}.tar.gz"


def _exe_name() -> str:
    return "rg.exe" if platform.system().lower() == "windows" else "rg"


def _candidate_urls(url: str) -> list[str]:
    urls = [url]
    if "github.com/" in url:
        for prefix in _GITHUB_MIRROR_PREFIXES:
            urls.append(f"{prefix}{url}")
    return urls


def _download_once(url: str, timeout: int) -> bytes:
    with urllib.request.urlopen(url, timeout=timeout) as resp:
        return resp.read()


def _download(url: str, timeout: int = 600) -> bytes:
    last_err: BaseException | None = None
    for candidate in _candidate_urls(url):
        print(f"fetching ripgrep: {candidate}", flush=True)
        try:
            return _download_once(candidate, timeout)
        except Exception as urllib_err:
            last_err = urllib_err
            print(f"urllib failed ({urllib_err!r})", flush=True)
            curl = shutil.which("curl") or shutil.which("curl.exe")
            if not curl:
                continue
            print("retrying with curl", flush=True)
            with tempfile.NamedTemporaryFile(delete=False) as tmp:
                tmp_path = tmp.name
            try:
                subprocess.check_call(
                    [curl, "-fsSL", "--retry", "3", "-o", tmp_path, candidate],
                    timeout=timeout,
                )
                return Path(tmp_path).read_bytes()
            except Exception as curl_err:
                last_err = curl_err
                print(f"curl failed ({curl_err!r})", flush=True)
            finally:
                Path(tmp_path).unlink(missing_ok=True)
    assert last_err is not None
    raise last_err


def _parse_sha256_payload(raw: str) -> str:
    """Extract a hex digest from GNU ``hash  name`` or CertUtil-style files."""
    for token in raw.replace("\r", "\n").split():
        t = token.strip().lower()
        if len(t) == 64 and all(c in "0123456789abcdef" for c in t):
            return t
    raise SystemExit(f"no sha256 digest found in checksum payload: {raw[:200]!r}")


def _verify(data: bytes, url: str) -> None:
    expected = os.environ.get("RG_SHA256", "")
    if expected == "skip":
        return
    if not expected:
        sha_url = url + ".sha256"
        raw = _download(sha_url, timeout=120).decode(errors="replace").strip()
        expected = _parse_sha256_payload(raw)
    else:
        expected = expected.strip().lower()
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected:
        raise SystemExit(f"ripgrep sha256 mismatch: {actual} != {expected}")


def _extract_rg(archive: Path, dest: Path) -> None:
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        if archive.suffix == ".zip" or archive.name.endswith(".zip"):
            with zipfile.ZipFile(archive) as zf:
                zf.extractall(tmp_path)
        else:
            with tarfile.open(archive, "r:gz") as tf:
                tf.extractall(tmp_path)
        found: Path | None = None
        for p in tmp_path.rglob("rg.exe" if dest.suffix == ".exe" else "rg"):
            if p.is_file():
                found = p
                break
        if found is None:
            raise SystemExit(f"rg binary not found inside archive {archive.name}")
        shutil.copy2(found, dest)
        dest.chmod(dest.stat().st_mode | 0o755)


def fetch_to(out_path: Path, *, target: str | None = None) -> Path:
    version = os.environ.get("RG_VERSION") or _DEFAULT_VERSION
    target = target or os.environ.get("RG_TARGET") or _host_target()
    name = _archive_name(version, target)
    url = os.environ.get("RG_URL") or f"{_GITHUB}/{version}/{name}"
    data = _download(url)
    _verify(data, url)

    out_path = out_path.resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(delete=False, suffix=Path(name).suffix) as tmp:
        tmp.write(data)
        archive = Path(tmp.name)
    try:
        _extract_rg(archive, out_path)
    finally:
        archive.unlink(missing_ok=True)
    print(f"ripgrep written: {out_path} ({out_path.stat().st_size} bytes)", flush=True)
    return out_path


def _server_bin() -> Path:
    # Docker copies this script to /fetch_ripgrep.py (no repo parents); only
    # --install-server walks parents[1]. Keep help text static so argparse
    # construction stays safe at filesystem root.
    return Path(__file__).resolve().parents[1] / "bin" / _exe_name()


def _desktop_bin() -> Path:
    desktop = Path(__file__).resolve().parents[2] / "desktop" / "resources" / "rg"
    return desktop / _exe_name()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "output",
        nargs="?",
        help="destination path for the rg binary (omit with --install-*)",
    )
    parser.add_argument(
        "--install-server",
        action="store_true",
        help="install to apps/server/bin/rg(.exe)",
    )
    parser.add_argument(
        "--install-desktop",
        action="store_true",
        help="install to apps/desktop/resources/rg/rg(.exe)",
    )
    parser.add_argument(
        "--target",
        default=None,
        help="rustc target triple (default: host, or RG_TARGET)",
    )
    args = parser.parse_args(argv)

    modes = sum(bool(x) for x in (args.output, args.install_server, args.install_desktop))
    if modes != 1:
        parser.error("specify exactly one of: output path | --install-server | --install-desktop")

    if args.install_server:
        out = _server_bin()
    elif args.install_desktop:
        out = _desktop_bin()
    else:
        out = Path(args.output)

    fetch_to(out, target=args.target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
