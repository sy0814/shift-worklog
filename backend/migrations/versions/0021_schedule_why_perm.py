"""角色权限加 schedule.why（看排班原因「为什么？」）。已有角色按以前的规则给默认值，升级后谁能看不变：
有改出勤 / 班组调班 / 名册 / 班组管理任一权限的 → 本车间（其中有「全厂」的 → 全厂）；其他 → 不能

Revision ID: 0021
Revises: 0020
"""

import sqlalchemy as sa
from alembic import op

revision = "0021"
down_revision = "0020"
branch_labels = None
depends_on = None

OLD = ("attendance.edit", "schedule.team_shift", "worker.manage", "team.manage")


def _roles(conn):
    roles = sa.table("roles", sa.column("id", sa.Integer), sa.column("permissions", sa.JSON))
    return roles, conn.execute(sa.select(roles.c.id, roles.c.permissions)).all()


def upgrade() -> None:
    conn = op.get_bind()
    roles, rows = _roles(conn)
    for rid, perms in rows:
        perms = dict(perms or {})
        if "schedule.why" not in perms:
            vals = [perms.get(k, "none") for k in OLD]
            perms["schedule.why"] = "all" if "all" in vals else "dept" if any(v != "none" for v in vals) else "none"
            conn.execute(roles.update().where(roles.c.id == rid).values(permissions=perms))


def downgrade() -> None:
    conn = op.get_bind()
    roles, rows = _roles(conn)
    for rid, perms in rows:
        perms = dict(perms or {})
        if perms.pop("schedule.why", None) is not None:
            conn.execute(roles.update().where(roles.c.id == rid).values(permissions=perms))
