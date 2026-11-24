"""roles (permission matrix) and accounts linked to roster workers

- 新表 roles，写入内置角色：班长、副班长（权限和以前的班长账号一样）、成员
- users 加 worker_id（账号对应名册里的人）、登录失败次数、锁定时间、最后登录时间
- workers 加 role_id
- 原来的班长账号（role = leader）：按姓名找名册里同名的人（优先同班组）关联上；没有就在名册里建一个，
  角色设为「班长」；账号 role 改为 staff，用户名和密码不变

Revision ID: 0010
Revises: 0009
"""
from datetime import date, datetime, timezone

from alembic import op
import sqlalchemy as sa


revision = '0010'
down_revision = '0009'
branch_labels = None
depends_on = None

PERMS = ["task.view", "task.create", "task.edit", "task.status", "task.handover", "task.discard", "task.edit_done",
         "photo.upload", "photo.delete", "translation.correct", "attendance.edit", "overtime.edit",
         "schedule.team_shift", "inspection.manage", "export", "worker.avatar", "worker.pin"]
LEADER = {k: "team" for k in PERMS} | {"task.view": "all", "task.edit_done": "none"}
MEMBER = {k: "none" for k in PERMS} | {"task.view": "team", "task.status": "self", "photo.upload": "self",
                                       "photo.delete": "self"}
ROLES = [("leader", "班长", "Šef smene", "Shift leader", LEADER, "password", True),
         ("deputy", "副班长", "Zamenik šefa", "Deputy leader", LEADER, "password", True),
         ("member", "成员", "Član ekipe", "Team member", MEMBER, "pin", False)]


def upgrade() -> None:
    op.create_table(
        'roles',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('code', sa.String(length=20), nullable=False),
        sa.Column('name_zh', sa.String(length=50), nullable=False),
        sa.Column('name_sr', sa.String(length=50), nullable=False),
        sa.Column('name_en', sa.String(length=50), nullable=False),
        sa.Column('permissions', sa.JSON(), nullable=False),
        sa.Column('login_mode', sa.String(length=10), nullable=False),
        sa.Column('show_on_top', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('is_builtin', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_roles')),
        sa.UniqueConstraint('code', name=op.f('uq_roles_code')),
    )
    with op.batch_alter_table('workers', schema=None) as b:
        b.add_column(sa.Column('role_id', sa.Integer(), nullable=True))
        b.create_foreign_key(b.f('fk_workers_role_id_roles'), 'roles', ['role_id'], ['id'])
    with op.batch_alter_table('users', schema=None) as b:
        b.add_column(sa.Column('worker_id', sa.Integer(), nullable=True))
        b.add_column(sa.Column('failed_logins', sa.Integer(), server_default='0', nullable=False))
        b.add_column(sa.Column('locked_until', sa.DateTime(timezone=True), nullable=True))
        b.add_column(sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True))
        b.create_unique_constraint(b.f('uq_users_worker_id'), ['worker_id'])
        b.create_foreign_key(b.f('fk_users_worker_id_workers'), 'workers', ['worker_id'], ['id'])

    conn = op.get_bind()
    roles = sa.table('roles', sa.column('id', sa.Integer), sa.column('code', sa.String),
                     sa.column('name_zh', sa.String), sa.column('name_sr', sa.String), sa.column('name_en', sa.String),
                     sa.column('permissions', sa.JSON), sa.column('login_mode', sa.String),
                     sa.column('show_on_top', sa.Boolean), sa.column('sort_order', sa.Integer),
                     sa.column('is_builtin', sa.Boolean))
    conn.execute(roles.insert(), [dict(code=c, name_zh=zh, name_sr=sr, name_en=en, permissions=p, login_mode=m,
                                       show_on_top=top, sort_order=i, is_builtin=True)
                                  for i, (c, zh, sr, en, p, m, top) in enumerate(ROLES)])
    leader_role = conn.execute(sa.text("SELECT id FROM roles WHERE code = 'leader'")).scalar()

    workers = sa.table('workers', sa.column('id', sa.Integer), sa.column('name', sa.String),
                       sa.column('team_id', sa.Integer), sa.column('is_active', sa.Boolean),
                       sa.column('created_at', sa.DateTime(timezone=True)), sa.column('extra', sa.JSON),
                       sa.column('role_id', sa.Integer))
    ws = sa.table('worker_schedules', sa.column('worker_id', sa.Integer), sa.column('effective_from', sa.Date),
                  sa.column('team_id', sa.Integer), sa.column('created_at', sa.DateTime(timezone=True)),
                  sa.column('holiday_off', sa.Boolean), sa.column('note', sa.String))
    now = datetime.now(timezone.utc)
    taken: set[int] = set()
    leaders = conn.execute(sa.text(
        "SELECT id, full_name, team_id, is_active FROM users WHERE role = 'leader' ORDER BY id")).all()
    for uid, name, team_id, active in leaders:
        cands = conn.execute(sa.text("SELECT id, team_id FROM workers WHERE TRIM(name) = :n ORDER BY id"),
                             {"n": (name or "").strip()}).all()
        cands = [c for c in cands if c[0] not in taken]
        cands.sort(key=lambda c: c[1] != team_id)  # 同班组的优先
        if cands:
            wid = cands[0][0]
        else:
            wid = conn.execute(workers.insert().values(name=name, team_id=team_id, is_active=bool(active),
                                                       created_at=now, extra={}).returning(workers.c.id)).scalar()
            conn.execute(ws.insert().values(worker_id=wid, effective_from=date(2000, 1, 1), team_id=team_id,
                                            created_at=now, holiday_off=False, note=''))
        taken.add(wid)
        conn.execute(sa.text("UPDATE workers SET role_id = :r WHERE id = :w"), {"r": leader_role, "w": wid})
        conn.execute(sa.text("UPDATE users SET worker_id = :w, role = 'staff' WHERE id = :u"), {"w": wid, "u": uid})


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("UPDATE users SET role = 'leader' WHERE role = 'staff'"))
    with op.batch_alter_table('users', schema=None) as b:
        b.drop_constraint(b.f('fk_users_worker_id_workers'), type_='foreignkey')
        b.drop_constraint(b.f('uq_users_worker_id'), type_='unique')
        b.drop_column('last_login_at')
        b.drop_column('locked_until')
        b.drop_column('failed_logins')
        b.drop_column('worker_id')
    with op.batch_alter_table('workers', schema=None) as b:
        b.drop_constraint(b.f('fk_workers_role_id_roles'), type_='foreignkey')
        b.drop_column('role_id')
    op.drop_table('roles')
