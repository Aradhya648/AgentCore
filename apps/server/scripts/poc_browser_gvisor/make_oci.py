"""Generate a runsc OCI bundle that mirrors the product sandbox shape.

Faithfully replicates ``agentcore/tools/sandbox/gvisor.py::_build_oci_config``:
- empty read-only rootfs; host ``/usr /lib /lib64 /bin /etc`` ro-bind mounted;
- tmpfs ``/tmp``; rw bind ``/scratch``; user nobody(65534); pid/ipc/uts/mount ns;
- memory/cpu/pids limits.

PoC deltas vs product (all reported as the "diff vs current OCI" findings):
- ``--browsers-path``: an EXTRA ro-bind (e.g. /opt/ms-playwright) so the sandbox
  can see Playwright's Chromium bundle, which lives outside /usr.
- ``/tmp`` tmpfs enlarged + explicit mode=1777 (Chromium scratch / shm spill).
- network namespace omitted in ``--net host`` mode (PoC's most-permissive path).
"""

from __future__ import annotations

import argparse
import json
import os
import sys

HOST_BIND_PATHS = ("/usr", "/lib", "/lib64", "/bin", "/etc")


def _host_binds() -> list[dict]:
    mounts = []
    for path in HOST_BIND_PATHS:
        if os.path.isdir(path):
            mounts.append(
                {
                    "destination": path,
                    "type": "bind",
                    "source": path,
                    "options": ["ro", "rbind", "nosuid"],
                }
            )
    return mounts


def build_config(args: argparse.Namespace) -> dict:
    if args.minimal:
        proc_args = ["/bin/echo", "gvisor-min-ok"]
        env = ["PATH=/usr/local/bin:/usr/bin:/bin", "HOME=/tmp"]
        cwd = "/tmp"
    else:
        proc_args = ["python3", "/scratch/browser_task.py"]
        env = [
            "PATH=/usr/local/bin:/usr/bin:/bin",
            "HOME=/tmp",
            "LANG=C.UTF-8",
            "PYTHONDONTWRITEBYTECODE=1",
            f"PLAYWRIGHT_BROWSERS_PATH={args.browsers_path}",
            f"POC_URL={args.url}",
            "POC_OUT=/scratch",
            "POC_SHOT_NAME=screenshot_l2.png",
        ]
        cwd = "/scratch"

    mounts = [
        {
            "destination": "/tmp",
            "type": "tmpfs",
            "source": "tmpfs",
            # product uses size=64m and no explicit mode; Chromium needs more
            # scratch (shm spill via --disable-dev-shm-usage) and a writable mode.
            "options": ["nosuid", "nodev", "mode=1777", f"size={args.tmp_size}"],
        }
    ]
    if not args.minimal:
        mounts.append(
            {
                "destination": "/scratch",
                "type": "bind",
                "source": args.scratch,
                "options": ["rw", "rbind", "nosuid", "nodev"],
            }
        )
        # THE KEY DIFF: Playwright's browser bundle lives outside /usr, so the
        # product's 5 host binds do not expose it. Add it explicitly (ro).
        mounts.append(
            {
                "destination": args.browsers_path,
                "type": "bind",
                "source": args.browsers_path,
                "options": ["ro", "rbind", "nosuid", "nodev"],
            }
        )
    mounts.extend(_host_binds())

    namespaces = [
        {"type": "pid"},
        {"type": "ipc"},
        {"type": "uts"},
        {"type": "mount"},
    ]
    # host network => share the container netns (no new network namespace).
    if args.net == "none":
        pass  # offline; runsc invoked with --network=none by the caller

    return {
        "ociVersion": "1.0.2",
        "process": {
            "terminal": False,
            "user": {"uid": args.uid, "gid": args.uid},
            "args": proc_args,
            "env": env,
            "cwd": cwd,
        },
        "root": {"path": "rootfs", "readonly": True},
        "mounts": mounts,
        "linux": {
            "resources": {
                "memory": {"limit": args.mem_mb * 1024 * 1024},
                "cpu": {"quota": int(args.cpus * 100000), "period": 100000},
                "pids": {"limit": args.pids},
            },
            "namespaces": namespaces,
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--bundle", required=True)
    ap.add_argument("--scratch", default="/tmp/poc-scratch")
    ap.add_argument("--browsers-path", default="/opt/ms-playwright")
    ap.add_argument("--url", default="https://example.com")
    ap.add_argument("--net", choices=["host", "none"], default="host")
    ap.add_argument("--mem-mb", type=int, default=2048)
    ap.add_argument("--cpus", type=float, default=2.0)
    ap.add_argument("--pids", type=int, default=512)
    ap.add_argument("--uid", type=int, default=65534)
    ap.add_argument("--tmp-size", default="512m")
    ap.add_argument("--minimal", action="store_true")
    args = ap.parse_args()

    os.makedirs(os.path.join(args.bundle, "rootfs"), exist_ok=True)
    config = build_config(args)
    with open(os.path.join(args.bundle, "config.json"), "w") as fh:
        json.dump(config, fh, indent=2)
    json.dump({"mounts": [m["destination"] for m in config["mounts"]]}, sys.stderr)
    sys.stderr.write("\n")
    print(os.path.join(args.bundle, "config.json"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
