"""attendance.code：工厂出勤月表里的原始写法（AL、SL、BT……），出勤页原样显示

Revision ID: 0023
Revises: 0022
"""

import sqlalchemy as sa
from alembic import op

revision = "0023"
down_revision = "0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("attendance") as b:
        b.add_column(sa.Column("code", sa.String(length=10), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("attendance") as b:
        b.drop_column("code")
