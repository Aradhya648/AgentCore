"""Download and verify the gVisor runsc binary at image build time.

Build-stage helper for ``apps/server/Dockerfile`` (stage ``runsc``) — stdlib
only, driven by env:

- ``RUNSC_URL``: release binary URL (default: official latest x86_64).
- ``RUNSC_SHA512``: expected digest; empty → fetch ``${RUNSC_URL}.sha512``;
  literal ``skip`` → no verification (mirrors without a digest file).

Usage: ``python fetch_runsc.py /out/runsc``
"""

from __future__ import annotations

import hashlib
import os
import sys
import urllib.request

_DEFAULT_URL = (
    "https://storage.googleapis.com/gvisor/releases/release/latest/x86_64/runsc"
)


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: fetch_runsc.py <output-path>", file=sys.stderr)
        return 2
    out_path = sys.argv[1]
    url = os.environ.get("RUNSC_URL") or _DEFAULT_URL
    print(f"fetching runsc: {url}", flush=True)
    data = urllib.request.urlopen(url, timeout=600).read()

    expected = os.environ.get("RUNSC_SHA512", "")
    if expected != "skip":
        if not expected:
            sha_url = url + ".sha512"
            expected = (
                urllib.request.urlopen(sha_url, timeout=120).read().decode().split()[0]
            )
        actual = hashlib.sha512(data).hexdigest()
        if actual != expected:
            print(f"runsc sha512 mismatch: {actual} != {expected}", file=sys.stderr)
            return 1

    with open(out_path, "wb") as f:
        f.write(data)
    print(f"runsc written: {out_path} ({len(data)} bytes)", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
