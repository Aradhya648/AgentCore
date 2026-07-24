"""PoC browser workload: navigate -> accessibility snapshot -> screenshot.

Runs identically in L1 (direct, in the container) and L2 (inside a runsc
sandbox). Emits a single machine-readable ``POC_METRICS_JSON=...`` line plus
human notes, and a non-zero exit on failure so the driver scripts can detect it.

Env knobs:
- ``POC_URL``        target URL (default https://example.com)
- ``POC_OUT``        directory to write the screenshot into (default /tmp/poc)
- ``POC_SHOT_NAME``  screenshot filename (default screenshot.png)
"""

from __future__ import annotations

import json
import os
import time
import traceback

URL = os.environ.get("POC_URL", "https://example.com")
OUT = os.environ.get("POC_OUT", "/tmp/poc")
SHOT = os.environ.get("POC_SHOT_NAME", "screenshot.png")

# gVisor / container-safe Chromium flags. --no-sandbox: Chromium's own
# setuid/namespace sandbox cannot nest inside gVisor (gVisor *is* the sandbox).
# --disable-dev-shm-usage: /dev/shm in the sandbox is small; route shm to /tmp.
# --disable-gpu: no GPU in the sandbox.
CHROME_ARGS = ["--no-sandbox", "--disable-dev-shm-usage", "--disable-gpu"]


def _count_nodes(node: dict | None) -> int:
    if not node:
        return 0
    total = 1
    for child in node.get("children", []) or []:
        total += _count_nodes(child)
    return total


def _accessibility_snapshot(page) -> dict:
    """Return a small summary of the a11y tree; try legacy API then ARIA."""
    # Legacy Accessibility API (dict tree).
    try:
        snap = page.accessibility.snapshot()
        if snap:
            return {
                "method": "accessibility.snapshot",
                "root_role": snap.get("role"),
                "root_name": (snap.get("name") or "")[:80],
                "node_count": _count_nodes(snap),
            }
    except Exception as exc:  # noqa: BLE001 - PoC records, never crashes here
        legacy_err = repr(exc)[:160]
    else:
        legacy_err = "returned empty"
    # Newer ARIA snapshot (YAML string).
    try:
        aria = page.locator("body").aria_snapshot()
        return {
            "method": "aria_snapshot",
            "legacy_error": legacy_err,
            "yaml_len": len(aria or ""),
            "yaml_head": (aria or "")[:200],
        }
    except Exception as exc:  # noqa: BLE001
        return {"method": "none", "legacy_error": legacy_err, "aria_error": repr(exc)[:160]}


def main() -> int:
    os.makedirs(OUT, exist_ok=True)
    shot_path = os.path.join(OUT, SHOT)
    metrics: dict = {"url": URL, "chrome_args": CHROME_ARGS, "out": shot_path}

    from playwright.sync_api import sync_playwright

    t0 = time.monotonic()
    with sync_playwright() as p:
        t_init = time.monotonic()
        browser = p.chromium.launch(headless=True, args=CHROME_ARGS)
        t_launch = time.monotonic()
        metrics["chromium_version"] = browser.version
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        resp = page.goto(URL, wait_until="load", timeout=45000)
        t_nav = time.monotonic()
        metrics["http_status"] = resp.status if resp else None
        metrics["title"] = page.title()
        metrics["a11y"] = _accessibility_snapshot(page)
        t_a11y = time.monotonic()
        page.screenshot(path=shot_path, full_page=True)
        t_shot = time.monotonic()
        browser.close()
    t_end = time.monotonic()

    metrics["screenshot_bytes"] = os.path.getsize(shot_path)
    with open(shot_path, "rb") as fh:
        metrics["screenshot_is_png"] = fh.read(8) == b"\x89PNG\r\n\x1a\n"
    metrics["timings_ms"] = {
        "playwright_init": round((t_init - t0) * 1000),
        "browser_launch_cold_start": round((t_launch - t_init) * 1000),
        "navigate": round((t_nav - t_launch) * 1000),
        "a11y_snapshot": round((t_a11y - t_nav) * 1000),
        "screenshot": round((t_shot - t_a11y) * 1000),
        "total": round((t_end - t0) * 1000),
    }

    print("POC_METRICS_JSON=" + json.dumps(metrics, ensure_ascii=False), flush=True)
    ok = bool(metrics["screenshot_is_png"]) and (metrics.get("http_status") == 200)
    print(f"POC_OK={ok}", flush=True)
    return 0 if ok else 3


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except Exception:  # noqa: BLE001 - surface full traceback as PoC evidence
        traceback.print_exc()
        print("POC_OK=False", flush=True)
        raise SystemExit(4) from None
