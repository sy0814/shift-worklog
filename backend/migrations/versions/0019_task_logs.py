"""task_logs：任务的班次日志（自由填写，自动翻译）

Revision ID: 0019
Revises: 0018
"""

import sqlalchemy as sa
from alembic import op

revision = "0019"
down_revision = "0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "task_logs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("client_id", sa.String(length=36), nullable=True),
        sa.Column("content_zh", sa.Text(), nullable=True),
        sa.Column("content_sr", sa.Text(), nullable=True),
        sa.Column("content_en", sa.Text(), nullable=True),
        sa.Column("source_lang", sa.String(length=5), nullable=False),
        sa.Column("translation_status", sa.String(length=10), nullable=False),
        sa.Column("shift_date", sa.Date(), nullable=False),
        sa.Column("shift_kind", sa.String(length=10), nullable=False),
        sa.Column("team_id", sa.Integer(), nullable=True),
        sa.Column("worker_id", sa.Integer(), nullable=True),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("deleted_by", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], name=op.f("fk_task_logs_task_id_tasks")),
        sa.ForeignKeyConstraint(["team_id"], ["teams.id"], name=op.f("fk_task_logs_team_id_teams")),
        sa.ForeignKeyConstraint(["worker_id"], ["workers.id"], name=op.f("fk_task_logs_worker_id_workers")),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_task_logs_created_by_users")),
        sa.ForeignKeyConstraint(["deleted_by"], ["users.id"], name=op.f("fk_task_logs_deleted_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task_logs")),
        sa.UniqueConstraint("client_id", name=op.f("uq_task_logs_client_id")),
    )
    op.create_index(op.f("ix_task_logs_task_id"), "task_logs", ["task_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_task_logs_task_id"), table_name="task_logs")
    op.drop_table("task_logs")
