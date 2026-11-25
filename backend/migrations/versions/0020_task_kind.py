"""tasks.kind：任务类型（故障维修 / 计划检修 / 巡查 / 其他），设备统计用。已有的巡查任务设为 inspection，其他为 other

Revision ID: 0020
Revises: 0019
"""

import sqlalchemy as sa
from alembic import op

revision = "0020"
down_revision = "0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("tasks") as b:
        b.add_column(sa.Column("kind", sa.String(length=12), server_default="other", nullable=False))
    op.execute("UPDATE tasks SET kind = 'inspection' WHERE inspection_id IS NOT NULL")


def downgrade() -> None:
    with op.batch_alter_table("tasks") as b:
        b.drop_column("kind")
