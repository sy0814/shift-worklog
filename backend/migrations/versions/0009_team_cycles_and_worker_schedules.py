"""team cycles (any length, main / merged) and worker schedule history

把原来的「倒班 offset + 基准日」「常白班」换成统一的循环设置：
  倒班：8 天 白白中中夜夜休休，循环第 1 天 = 基准日 - offset，主班组
  常白班：7 天 白×5 休休，从周一开始，节假日休息，合并显示
  不固定（manual）：不变
并给每个员工建第一条班组记录（从 2000-01-01 起 = 一直以来）。

Revision ID: 0009
Revises: 0008
"""
from datetime import date, datetime, timedelta, timezone

from alembic import op
import sqlalchemy as sa


revision = '0009'
down_revision = '0008'
branch_labels = None
depends_on = None

CYCLE = ["day", "day", "middle", "middle", "night", "night", "off", "off"]
WEEKDAYS = ["day", "day", "day", "day", "day", "off", "off"]
EPOCH = date(2000, 1, 1)


def upgrade() -> None:
    with op.batch_alter_table('teams', schema=None) as b:
        b.add_column(sa.Column('pattern', sa.JSON(), nullable=True))
        b.add_column(sa.Column('cycle_start', sa.Date(), nullable=True))
        b.add_column(sa.Column('holiday_off', sa.Boolean(), server_default=sa.false(), nullable=False))
        b.add_column(sa.Column('is_main', sa.Boolean(), server_default=sa.false(), nullable=False))

    op.create_table(
        'worker_schedules',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('worker_id', sa.Integer(), nullable=False),
        sa.Column('effective_from', sa.Date(), nullable=False),
        sa.Column('team_id', sa.Integer(), nullable=True),
        sa.Column('pattern', sa.JSON(), nullable=True),
        sa.Column('cycle_start', sa.Date(), nullable=True),
        sa.Column('holiday_off', sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.Column('note', sa.String(length=200), server_default='', nullable=False),
        sa.Column('created_by', sa.Integer(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['created_by'], ['users.id'], name=op.f('fk_worker_schedules_created_by_users')),
        sa.ForeignKeyConstraint(['team_id'], ['teams.id'], name=op.f('fk_worker_schedules_team_id_teams')),
        sa.ForeignKeyConstraint(['worker_id'], ['workers.id'], name=op.f('fk_worker_schedules_worker_id_workers')),
        sa.PrimaryKeyConstraint('id', name=op.f('pk_worker_schedules')),
        sa.UniqueConstraint('worker_id', 'effective_from', name=op.f('uq_worker_schedules_worker_id')),
    )
    with op.batch_alter_table('worker_schedules', schema=None) as b:
        b.create_index(b.f('ix_worker_schedules_worker_id'), ['worker_id'], unique=False)

    # ---- 数据转换 ----
    conn = op.get_bind()
    teams = sa.table('teams', sa.column('id', sa.Integer), sa.column('kind', sa.String),
                     sa.column('cycle_offset', sa.Integer), sa.column('pattern', sa.JSON),
                     sa.column('cycle_start', sa.Date), sa.column('holiday_off', sa.Boolean),
                     sa.column('is_main', sa.Boolean))
    cfg = conn.execute(sa.text("SELECT base_date FROM shift_config WHERE id = 1")).first()
    base = cfg[0] if cfg else date(2026, 11, 1)
    if isinstance(base, str):
        base = date.fromisoformat(base[:10])
    monday = base - timedelta(days=base.weekday())
    for tid, kind, off in conn.execute(sa.select(teams.c.id, teams.c.kind, teams.c.cycle_offset)).all():
        if kind == 'rotating':
            vals = dict(kind='cycle', pattern=CYCLE, cycle_start=base - timedelta(days=off or 0),
                        holiday_off=False, is_main=True)
        elif kind == 'day':
            vals = dict(kind='cycle', pattern=WEEKDAYS, cycle_start=monday, holiday_off=True, is_main=False)
        else:
            vals = dict(kind='manual', pattern=None, cycle_start=None, holiday_off=False, is_main=False)
        conn.execute(teams.update().where(teams.c.id == tid).values(**vals))

    ws = sa.table('worker_schedules', sa.column('worker_id', sa.Integer), sa.column('effective_from', sa.Date),
                  sa.column('team_id', sa.Integer), sa.column('created_at', sa.DateTime(timezone=True)),
                  sa.column('holiday_off', sa.Boolean), sa.column('note', sa.String))
    now = datetime.now(timezone.utc)
    rows = [dict(worker_id=w, effective_from=EPOCH, team_id=t, created_at=now, holiday_off=False, note='')
            for w, t in conn.execute(sa.text("SELECT id, team_id FROM workers")).all()]
    if rows:
        conn.execute(ws.insert(), rows)

    with op.batch_alter_table('teams', schema=None) as b:
        b.drop_column('cycle_offset')
    with op.batch_alter_table('shift_config', schema=None) as b:
        b.drop_column('base_date')


def downgrade() -> None:
    with op.batch_alter_table('shift_config', schema=None) as b:
        b.add_column(sa.Column('base_date', sa.Date(), server_default='2026-11-01', nullable=False))
    with op.batch_alter_table('teams', schema=None) as b:
        b.add_column(sa.Column('cycle_offset', sa.Integer(), nullable=True))
    conn = op.get_bind()
    base = date(2026, 11, 1)
    for tid, pattern, start, is_main in conn.execute(sa.text(
            "SELECT id, pattern, cycle_start, is_main FROM teams")).all():
        if isinstance(start, str):
            start = date.fromisoformat(start[:10])
        if is_main and start:
            conn.execute(sa.text("UPDATE teams SET kind='rotating', cycle_offset=:o WHERE id=:i"),
                         {"o": (base - start).days % 8, "i": tid})
        elif start:
            conn.execute(sa.text("UPDATE teams SET kind='day' WHERE id=:i"), {"i": tid})
    with op.batch_alter_table('worker_schedules', schema=None) as b:
        b.drop_index(b.f('ix_worker_schedules_worker_id'))
    op.drop_table('worker_schedules')
    with op.batch_alter_table('teams', schema=None) as b:
        b.drop_column('is_main')
        b.drop_column('holiday_off')
        b.drop_column('cycle_start')
        b.drop_column('pattern')
