"""less_interrupt default: team_kickoff skip → rules

Revision ID: d5f1a8c2e9b4
Revises: c4e8a1f2b9d7
Create Date: 2026-08-01 04:10:00.000000

Only changes the column DEFAULT for new conversation rows.
Existing permission_axes JSON is left untouched (re-pick recipe to refresh).
"""

from collections.abc import Sequence

from alembic import op

revision: str = "d5f1a8c2e9b4"
down_revision: str | None = "c4e8a1f2b9d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW = (
    '\'{"file_write":"session","command":"auto",'
    '"team_kickoff":"rules","host":"ask"}\'::jsonb'
)
_OLD = (
    '\'{"file_write":"session","command":"auto",'
    '"team_kickoff":"skip","host":"ask"}\'::jsonb'
)


def upgrade() -> None:
    op.execute(
        f"ALTER TABLE conversations ALTER COLUMN permission_axes SET DEFAULT {_NEW}"
    )


def downgrade() -> None:
    op.execute(
        f"ALTER TABLE conversations ALTER COLUMN permission_axes SET DEFAULT {_OLD}"
    )
