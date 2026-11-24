"""班组调班可以填自定义时间段

Revision ID: 0014
Revises: 0013
"""

import sqlalchemy as sa
from alembic import op

revision = "0014"
down_revision = "0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("team_shift_overrides") as b:
        b.add_column(sa.Column("hours", sa.String(length=60), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("team_shift_overrides") as b:
        b.drop_column("hours")
