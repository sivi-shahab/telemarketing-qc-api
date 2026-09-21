"""stats_snapshots: add scope_key so scoped roles (AM/TL/Agent/QC/campaign-tag) can be cached too

Previously ``get_or_build_stats_snapshot`` only cached the single GLOBAL
snapshot (one row per WIB day, unique on ``snapshot_date``). Every scoped
role (Area Manager, Team Leader, Sales Agent, QC Support/QC own-assignment,
and any role tagged to a campaign) bypassed the cache entirely and called
``compute_stats_snapshot`` fresh on every request — and since one Stats page
load hits 3 endpoints (``/stats/overview``, ``/stats/campaigns_monthly``,
``/stats/hierarchy``) plus a 30s auto-refresh poll, that's a full recompute
several times a minute per open scoped-user tab.

``scope_key`` identifies the caller's data scope (a hash of their allowed
customer/ticket ids + roster, see ``api/routers/stats.py:_scope_key_for``)
so the SAME scope now hits the SAME cached row, while the empty string
(``""``) is reserved for the global snapshot — preserving the existing
one-row-per-day behaviour for the global cache untouched.

Revision ID: 0054  (monolit 0056)
Revises: 0053
Create Date: 2026-09-17 00:10:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0054"
down_revision: Union[str, None] = "0053"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "stats_snapshots",
        sa.Column("scope_key", sa.String(length=64), nullable=False, server_default=""),
    )
    op.drop_constraint("stats_snapshots_snapshot_date_key", "stats_snapshots", type_="unique")
    op.create_unique_constraint(
        "uq_stats_snapshots_date_scope", "stats_snapshots", ["snapshot_date", "scope_key"]
    )


def downgrade() -> None:
    op.drop_constraint("uq_stats_snapshots_date_scope", "stats_snapshots", type_="unique")
    # Scoped rows (scope_key != '') would collide on snapshot_date alone; drop
    # them before restoring the old single-row-per-day uniqueness.
    op.execute("DELETE FROM stats_snapshots WHERE scope_key <> ''")
    op.create_unique_constraint(
        "stats_snapshots_snapshot_date_key", "stats_snapshots", ["snapshot_date"]
    )
    op.drop_column("stats_snapshots", "scope_key")
