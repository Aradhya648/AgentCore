"""Resource caps for shared spaces (v1 — not billing quota; abuse floor).

Concrete numbers are implementation defaults for the proposal's open item
「防滥用上限的具体数值」. Tunable via settings; keep conservative.
"""

from __future__ import annotations

# Max spaces a single user may own.
DEFAULT_MAX_SPACES_PER_OWNER = 10
# Max members (accepted + pending) per space, including the owner.
DEFAULT_MAX_MEMBERS_PER_SPACE = 20
# Soft disk cap for one space's on-disk tree (bytes).
DEFAULT_MAX_SPACE_BYTES = 1 * 1024 * 1024 * 1024  # 1 GiB
# Invite sends per user per rolling window.
DEFAULT_INVITE_RATE_MAX = 20
DEFAULT_INVITE_RATE_WINDOW_SECONDS = 3600
