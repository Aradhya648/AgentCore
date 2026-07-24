"""OCI config for a long-lived browser sandbox (mirrors the validated PoC bundle).

Deltas vs ``gvisor.py::_build_oci_config`` (per the PoC "diff vs current OCI" list;
browser-session ONLY — code_execute's limits are untouched):
- an EXTRA ro-bind for Playwright's Chromium bundle (lives outside /usr);
- /tmp tmpfs enlarged (Chromium shm spill via --disable-dev-shm-usage);
- higher memory / pids / cpu (Chromium is multi-process, ~1–2GB observed);
- a network namespace referenced BY PATH so runsc netstack clones the veth
  (the PoC proved an empty/absent netns yields no connectivity);
- long-lived: the driver reads stdin forever (no timeout in the OCI; the host
  enforces per-command deadlines + idle/lifetime TTL).
"""

from __future__ import annotations

import os

_HOST_BIND_PATHS = ("/usr", "/lib", "/lib64", "/bin", "/etc")


def build_browser_oci(
    *,
    scratch_dir: str,
    browsers_path: str,
    netns_path: str,
    proxy_url: str,
    driver_rel_path: str = "browser_driver.py",
    width: int,
    height: int,
    jpeg_quality: int,
    memory_limit_mb: int,
    pids_limit: int,
    cpu_limit: float,
) -> dict:
    """Build the runsc OCI config dict for one browser session."""
    mounts = [
        {
            "destination": "/tmp",
            "type": "tmpfs",
            "source": "tmpfs",
            "options": ["nosuid", "nodev", "mode=1777", "size=512m"],
        },
        {
            "destination": "/scratch",
            "type": "bind",
            "source": scratch_dir,
            "options": ["rw", "rbind", "nosuid", "nodev"],
        },
        # THE key diff: Playwright's Chromium bundle lives outside /usr, so the
        # product's 5 host binds don't expose it. Add exactly this one (ro).
        {
            "destination": browsers_path,
            "type": "bind",
            "source": browsers_path,
            "options": ["ro", "rbind", "nosuid", "nodev"],
        },
    ]
    for path in _HOST_BIND_PATHS:
        if os.path.isdir(path):
            mounts.append(
                {
                    "destination": path,
                    "type": "bind",
                    "source": path,
                    "options": ["ro", "rbind", "nosuid"],
                }
            )

    return {
        "ociVersion": "1.0.2",
        "process": {
            "terminal": False,
            "user": {"uid": 65534, "gid": 65534},
            "args": ["python3", "-u", f"/scratch/{driver_rel_path}"],
            "env": [
                "PATH=/usr/local/bin:/usr/bin:/bin",
                "HOME=/tmp",
                "LANG=C.UTF-8",
                "PYTHONDONTWRITEBYTECODE=1",
                f"PLAYWRIGHT_BROWSERS_PATH={browsers_path}",
                f"BROWSER_PROXY={proxy_url}",
                f"BROWSER_WIDTH={width}",
                f"BROWSER_HEIGHT={height}",
                f"BROWSER_JPEG_Q={jpeg_quality}",
            ],
            "cwd": "/scratch",
        },
        "root": {"path": "rootfs", "readonly": True},
        "mounts": mounts,
        "linux": {
            "resources": {
                "memory": {"limit": memory_limit_mb * 1024 * 1024},
                "cpu": {"quota": int(cpu_limit * 100000), "period": 100000},
                "pids": {"limit": pids_limit},
            },
            # Reference the veth netns by PATH so netstack clones its interfaces +
            # routes (PoC finding: `ip netns exec` alone leaves netstack empty).
            "namespaces": [
                {"type": "pid"},
                {"type": "ipc"},
                {"type": "uts"},
                {"type": "mount"},
                {"type": "network", "path": netns_path},
            ],
        },
    }
