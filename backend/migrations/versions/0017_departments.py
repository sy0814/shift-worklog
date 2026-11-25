"""departments (workshops): a layer above teams

- 新表 departments，建一个默认车间（id=1），已有的班组、员工、设备、巡查项都归它
- teams.department_id（必填）、workers.department_id、equipment.department_id（空 = 全厂共用）、
  inspection_templates.department_id（必填）、ai_reports.department_id
- 角色权限加「本车间」范围（dept）：已有角色里的「全部」（all）改成「本车间」——以前只有一个车间，意思不变；
  以后建了别的车间，班长也不会自动看到别的车间。新权限 worker.manage / team.manage / analysis 默认 none
- 内置角色「车间管理员」（dept_admin）由程序启动时补上（permissions.ensure_builtin_roles）

Revision ID: 0017
Revises: 0016
"""

from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "0017"
down_revision = "0016"
branch_labels = None
depends_on = None

# 允许 dept 范围的权限（和 app/permissions.py 的 PERMS 一致）
DEPT_OK = {"task.view", "task.create", "task.edit", "task.status", "task.handover", "task.discard",
           "task.edit_done", "photo.upload", "photo.delete", "translation.correct", "attendance.edit",
           "overtime.edit", "schedule.team_shift", "inspection.manage", "export", "worker.avatar", "worker.pin",
           "equipment.manage", "project.manage"}
NEW_PERMS = ("worker.manage", "team.manage", "analysis")


def upgrade() -> None:
    op.create_table(
        "departments",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(length=20), nullable=False),
        sa.Column("name_zh", sa.String(length=100), nullable=False),
        sa.Column("name_sr", sa.String(length=100), nullable=False),
        sa.Column("name_en", sa.String(length=100), nullable=False),
        sa.Column("sort_order", sa.Integer(), nullable=False),
        sa.Column("is_active", sa.Boolean(), server_default=sa.true(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_departments")),
        sa.UniqueConstraint("code", name=op.f("uq_departments_code")),
    )
    conn = op.get_bind()
    deps = sa.table("departments", sa.column("id", sa.Integer), sa.column("code", sa.String),
                    sa.column("name_zh", sa.String), sa.column("name_sr", sa.String), sa.column("name_en", sa.String),
                    sa.column("sort_order", sa.Integer), sa.column("is_active", sa.Boolean),
                    sa.column("created_at", sa.DateTime(timezone=True)))
    conn.execute(deps.insert(), [dict(id=1, code="D1", name_zh="默认车间", name_sr="Podrazumevani pogon",
                                      name_en="Default workshop", sort_order=0, is_active=True,
                                      created_at=datetime.now(timezone.utc))])
    if conn.dialect.name == "postgresql":  # 手动写了 id，序列要跟上
        conn.execute(sa.text("SELECT setval(pg_get_serial_sequence('departments', 'id'), 1)"))

    # 必填列：先加可空列、填上默认车间，再改成非空
    for table in ("teams", "inspection_templates"):
        with op.batch_alter_table(table) as b:
            b.add_column(sa.Column("department_id", sa.Integer(), nullable=True))
        conn.execute(sa.text(f"UPDATE {table} SET department_id = 1"))
        with op.batch_alter_table(table) as b:
            b.alter_column("department_id", existing_type=sa.Integer(), nullable=False)
            b.create_index(b.f(f"ix_{table}_department_id"), ["department_id"], unique=False)
            b.create_foreign_key(b.f(f"fk_{table}_department_id_departments"), "departments", ["department_id"], ["id"])

    for table, index in (("workers", True), ("equipment", True), ("ai_reports", False)):
        with op.batch_alter_table(table) as b:
            b.add_column(sa.Column("department_id", sa.Integer(), nullable=True))
            if index:
                b.create_index(b.f(f"ix_{table}_department_id"), ["department_id"], unique=False)
            b.create_foreign_key(b.f(f"fk_{table}_department_id_departments"), "departments", ["department_id"], ["id"])
    conn.execute(sa.text("UPDATE workers SET department_id = 1"))
    conn.execute(sa.text("UPDATE equipment SET department_id = 1"))
    conn.execute(sa.text("UPDATE ai_reports SET department_id = 1"))

    roles = sa.table("roles", sa.column("id", sa.Integer), sa.column("permissions", sa.JSON))
    for rid, perms in conn.execute(sa.select(roles.c.id, roles.c.permissions)).all():
        perms = dict(perms or {})
        for k, v in list(perms.items()):
            if v == "all" and k in DEPT_OK:
                perms[k] = "dept"
        for k in NEW_PERMS:
            perms.setdefault(k, "none")
        conn.execute(roles.update().where(roles.c.id == rid).values(permissions=perms))


def downgrade() -> None:
    conn = op.get_bind()
    roles = sa.table("roles", sa.column("id", sa.Integer), sa.column("permissions", sa.JSON))
    for rid, perms in conn.execute(sa.select(roles.c.id, roles.c.permissions)).all():
        perms = {k: ("all" if v == "dept" else v) for k, v in dict(perms or {}).items() if k not in NEW_PERMS}
        conn.execute(roles.update().where(roles.c.id == rid).values(permissions=perms))
    conn.execute(sa.text("UPDATE workers SET role_id = NULL WHERE role_id IN (SELECT id FROM roles WHERE code = 'dept_admin')"))
    conn.execute(sa.text("DELETE FROM roles WHERE code = 'dept_admin'"))
    for table, index in (("ai_reports", False), ("equipment", True), ("workers", True),
                         ("inspection_templates", True), ("teams", True)):
        with op.batch_alter_table(table) as b:
            b.drop_constraint(b.f(f"fk_{table}_department_id_departments"), type_="foreignkey")
            if index:
                b.drop_index(b.f(f"ix_{table}_department_id"))
            b.drop_column("department_id")
    op.drop_table("departments")
