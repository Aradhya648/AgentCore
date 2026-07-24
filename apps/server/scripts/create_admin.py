"""Create or promote an admin user (production bootstrap).

Registration is invite-gated (D6), and a fresh deployment has no invites — so the
very first admin cannot self-register. Run this once on a new deployment to mint
the initial admin, who can then issue invite codes from the app's 成员 settings.

Run from ``apps/server``::

    uv run python scripts/create_admin.py <username>

The password comes from the ``ADMIN_PASSWORD`` env var, or is prompted for
(hidden input) when unset. Safe to re-run:
- a non-existent user is created with role ``admin``;
- an existing non-admin user is promoted to ``admin``;
- a password is only set when the user has none (existing passwords are kept).
"""

from __future__ import annotations

import asyncio
import getpass
import os
import sys

from agentcore.db import async_session_factory
from agentcore.db.repositories import CredentialsRepository, UserRepository
from agentcore.security import hash_password

_MIN_PASSWORD_LENGTH = 8


async def _create_admin(username: str, password: str) -> None:
    async with async_session_factory() as session:
        users = UserRepository(session)
        creds = CredentialsRepository(session)

        user = await users.get_by_username(username)
        if user is None:
            user = await users.create(username=username, display_name=username, role="admin")
            print(f"created admin {username!r} (id={user.user_id})")
        elif user.role != "admin":
            await users.set_role(user.user_id, "admin")
            print(f"promoted {username!r} to admin (id={user.user_id})")
        else:
            print(f"{username!r} is already an admin (id={user.user_id})")

        # The bootstrap operator account should never be cost-capped (决策④):
        # mark it is_unlimited so it can run/triage freely. Revoke later with
        # scripts/set_quota.py --no-unlimited if you want it metered.
        if not user.is_unlimited:
            await users.set_quota(user.user_id, is_unlimited=True)
            print(f"marked {username!r} is_unlimited (no quota cap)")

        if await creds.get_by_user_id(user.user_id) is None:
            await creds.create(user_id=user.user_id, password_hash=hash_password(password))
            print(f"set password for {username!r}")
        else:
            print(f"{username!r} already has a password (left unchanged)")

    print("\nadmin ready. Log in, then issue invite codes from 设置 → 成员.")


def _read_args() -> tuple[str, str]:
    if len(sys.argv) != 2 or not sys.argv[1].strip():
        print("usage: python scripts/create_admin.py <username>", file=sys.stderr)
        raise SystemExit(2)
    username = sys.argv[1].strip()

    password = os.environ.get("ADMIN_PASSWORD") or getpass.getpass("Admin password: ")
    if len(password) < _MIN_PASSWORD_LENGTH:
        print(
            f"password must be at least {_MIN_PASSWORD_LENGTH} characters",
            file=sys.stderr,
        )
        raise SystemExit(2)
    return username, password


if __name__ == "__main__":
    name, pw = _read_args()
    asyncio.run(_create_admin(name, pw))
