"""Pre-build connectivity probe: are the runsc + Playwright mirrors reachable?

Run inside python:3.12-slim before the (long) image build to fail fast instead
of wasting a multi-minute build on an unreachable download host.
"""

from __future__ import annotations

import sys
import urllib.request

TARGETS = {
    "runsc_google": "https://storage.googleapis.com/gvisor/releases/release/latest/x86_64/runsc",
    "pw_default_azureedge": "https://playwright.azureedge.net/",
    "pw_default_cdn": "https://cdn.playwright.dev/",
    "pw_npmmirror_builds": "https://cdn.npmmirror.com/binaries/playwright/builds/",
    "pypi_tsinghua": "https://pypi.tuna.tsinghua.edu.cn/simple/playwright/",
}


def check(name: str, url: str) -> None:
    try:
        req = urllib.request.Request(url, method="GET")
        with urllib.request.urlopen(req, timeout=30) as resp:
            print(f"{name}: OK status={resp.status}")
    except Exception as exc:  # noqa: BLE001
        print(f"{name}: FAIL {type(exc).__name__} {str(exc)[:160]}")


def main() -> int:
    for name, url in TARGETS.items():
        check(name, url)
    return 0


if __name__ == "__main__":
    sys.exit(main())
