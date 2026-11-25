"""tasks.transferable：普通任务、巡查生成的任务也可以设「不可移交」

Revision ID: 0018
Revises: 0017
"""

import sqlalchemy as sa
from alembic import op

revision = "0018"
down_revision = "0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as b:
        b.add_column(sa.Column("transferable", sa.Boolean(), server_default=sa.true(), nullable=False))


def downgrade() -> None:
    with op.batch_alter_table("tasks") as b:
        b.drop_column("transferable")
