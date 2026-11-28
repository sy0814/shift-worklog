"""项目计划开始时间（到时间前子项目不显示）、定期巡查「小项目由当班自己添加」

Revision ID: 0024
Revises: 0023
"""

import sqlalchemy as sa
from alembic import op

revision = "0024"
down_revision = "0023"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("projects") as b:
        b.add_column(sa.Column("start_at", sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column("lead_minutes", sa.Integer(), nullable=False, server_default="30"))
        b.add_column(sa.Column("open_items", sa.Boolean(), nullable=False, server_default=sa.false()))
        b.add_column(sa.Column("shift_date", sa.Date(), nullable=True))
        b.add_column(sa.Column("shift_kind", sa.String(length=10), nullable=True))
        b.add_column(sa.Column("closed_empty", sa.Boolean(), nullable=False, server_default=sa.false()))
    with op.batch_alter_table("tasks") as b:
        b.add_column(sa.Column("visible_from", sa.DateTime(timezone=True), nullable=True))
    with op.batch_alter_table("inspection_templates") as b:
        b.add_column(sa.Column("open_items", sa.Boolean(), nullable=False, server_default=sa.false()))


def downgrade() -> None:
    with op.batch_alter_table("inspection_templates") as b:
        b.drop_column("open_items")
    with op.batch_alter_table("tasks") as b:
        b.drop_column("visible_from")
    with op.batch_alter_table("projects") as b:
        for c in ("closed_empty", "shift_kind", "shift_date", "open_items", "lead_minutes", "start_at"):
            b.drop_column(c)
