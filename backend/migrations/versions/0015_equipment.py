"""设备台账 + 任务关联设备 + 角色权限 equipment.manage

Revision ID: 0015
Revises: 0014
"""

import sqlalchemy as sa
from alembic import op

revision = "0015"
down_revision = "0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "equipment",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=60), nullable=False),
        sa.Column("name_zh", sa.String(length=200), nullable=True),
        sa.Column("name_sr", sa.String(length=200), nullable=True),
        sa.Column("name_en", sa.String(length=200), nullable=True),
        sa.Column("area_zh", sa.String(length=200), nullable=True),
        sa.Column("area_sr", sa.String(length=200), nullable=True),
        sa.Column("area_en", sa.String(length=200), nullable=True),
        sa.Column("note_zh", sa.Text(), nullable=True),
        sa.Column("note_sr", sa.Text(), nullable=True),
        sa.Column("note_en", sa.Text(), nullable=True),
        sa.Column("model", sa.String(length=200), server_default="", nullable=False),
        sa.Column("source_lang", sa.String(length=5), nullable=False),
        sa.Column("translation_status", sa.String(length=10), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_by", sa.Integer(), nullable=False),
        sa.Column("updated_by", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name=op.f("fk_equipment_created_by_users")),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], name=op.f("fk_equipment_updated_by_users")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_equipment")),
        sa.UniqueConstraint("code", name=op.f("uq_equipment_code")),
    )
    with op.batch_alter_table("tasks") as b:
        b.add_column(sa.Column("equipment_id", sa.Integer(), nullable=True))
        b.create_index(b.f("ix_tasks_equipment_id"), ["equipment_id"], unique=False)
        b.create_foreign_key(b.f("fk_tasks_equipment_id_equipment"), "equipment", ["equipment_id"], ["id"])
    conn = op.get_bind()
    roles = sa.table("roles", sa.column("id", sa.Integer), sa.column("code", sa.String), sa.column("permissions", sa.JSON))
    for rid, code, perms in conn.execute(sa.select(roles.c.id, roles.c.code, roles.c.permissions)).all():
        perms = dict(perms or {})
        perms.setdefault("equipment.manage", "all" if code in ("leader", "deputy") else "none")
        conn.execute(roles.update().where(roles.c.id == rid).values(permissions=perms))


def downgrade() -> None:
    with op.batch_alter_table("tasks") as b:
        b.drop_constraint(b.f("fk_tasks_equipment_id_equipment"), type_="foreignkey")
        b.drop_index(b.f("ix_tasks_equipment_id"))
        b.drop_column("equipment_id")
    op.drop_table("equipment")
