"""数据库迁移测试。默认用 SQLite；设置环境变量 TEST_PG_URL 时同时在 PostgreSQL 上跑。

TEST_PG_URL 指向一个可以随便清空的空库，例如 postgresql+psycopg://postgres@/mig?host=/tmp&port=5433
"""

import os
import shutil
import uuid

import pytest
from alembic import command
from sqlalchemy import inspect, text
from sqlalchemy.exc import DBAPIError

from app import migrate
from app.db import Base, make_engine

EXTRA = '''
"""练习用：给 workers 加两列（一列可空，一列非空带默认值）"""
from alembic import op
import sqlalchemy as sa

revision = "practice"
down_revision = "{head}"
branch_labels = None
depends_on = None


def upgrade():
    with op.batch_alter_table("workers") as b:
        b.add_column(sa.Column("phone", sa.String(30), nullable=True))
        b.add_column(sa.Column("shift_note", sa.String(50), nullable=False, server_default="n/a"))


def downgrade():
    with op.batch_alter_table("workers") as b:
        b.drop_column("shift_note")
        b.drop_column("phone")
'''


def _urls(tmp_path):
    urls = [("sqlite", f"sqlite:///{tmp_path}/m.db")]
    if os.environ.get("TEST_PG_URL"):
        urls.append(("postgresql", os.environ["TEST_PG_URL"]))
    return urls


@pytest.fixture(params=["sqlite", "postgresql"])
def engine(request, tmp_path):
    url = dict(_urls(tmp_path)).get(request.param)
    if url is None:
        pytest.skip("没设置 TEST_PG_URL")
    eng = make_engine(url)
    if request.param == "postgresql":  # 清空
        with eng.begin() as c:
            c.execute(text("DROP SCHEMA public CASCADE; CREATE SCHEMA public"))
    yield eng
    eng.dispose()


def test_migrations_match_models(engine):
    """从空库执行全部迁移后，结构必须和 app/models.py 完全一致（改了模型忘写迁移会在这里失败）。"""
    migrate.upgrade(engine)
    with engine.connect() as c:
        assert migrate.current_revision(c) == migrate.head_revision()
        assert migrate.schema_diff(c) == []


def test_audit_trigger_installed_by_migration(engine):
    migrate.upgrade(engine)
    with engine.connect() as c:
        c.execute(text("INSERT INTO audit_log (at, action, entity, entity_id) VALUES (CURRENT_TIMESTAMP, 'x', 'y', '1')"))
        c.commit()
        with pytest.raises(DBAPIError):
            c.execute(text("UPDATE audit_log SET action = 'z'"))
        c.rollback()


def _seed(c):
    if not c.execute(text("SELECT count(*) FROM departments")).scalar():  # 迁移 0017 会建默认车间；create_all 不会
        c.execute(text("INSERT INTO departments (id, code, name_zh, name_sr, name_en, sort_order, is_active, created_at) "
                       "VALUES (1, 'D1', '车间', 'Pogon', 'Workshop', 0, true, CURRENT_TIMESTAMP)"))
    c.execute(text("INSERT INTO teams (id, code, name_zh, name_sr, name_en, kind, pattern, cycle_start, holiday_off, "
                   "is_main, sort_order, department_id) VALUES (1, 'T1', '1班', 'Smena 1', 'Team 1', 'cycle', "
                   "'[\"day\",\"day\",\"middle\",\"middle\",\"night\",\"night\",\"off\",\"off\"]', "
                   "'2026-10-28', false, true, 0, 1)"))
    c.execute(text("INSERT INTO users (id, username, password_hash, full_name, role, team_id, lang, is_active, created_at) "
                   "VALUES (1, 'u', 'h', 'U', 'leader', 1, 'zh', true, CURRENT_TIMESTAMP)"))
    c.execute(text("INSERT INTO workers (id, name, team_id, is_active, created_at) VALUES (1, 'Petar', 1, true, CURRENT_TIMESTAMP)"))
    c.execute(text(
        "INSERT INTO tasks (id, client_id, content_zh, source_lang, translation_status, translation_attempts, manual_fields, "
        "team_id, origin_team_id, status, shift_date, shift_kind, chain_started_at, handover_count, created_by, updated_by, "
        "recorded_at, created_at, updated_at) VALUES (1, :cid, '检查球磨机', 'zh', 'pending', 0, '[]', 1, 1, 'not_started', "
        "'2026-11-21', 'day', CURRENT_TIMESTAMP, 0, 1, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"),
        {"cid": str(uuid.uuid4())})
    c.execute(text("INSERT INTO task_workers (task_id, worker_id) VALUES (1, 1)"))
    c.execute(text("INSERT INTO audit_log (at, user_id, action, entity, entity_id) VALUES (CURRENT_TIMESTAMP, 1, 'create', 'task', '1')"))


def test_upgrade_and_downgrade_keep_data(engine, tmp_path):
    """有数据的库升级（加列）、再退回，数据都不丢。"""
    scripts = tmp_path / "migrations"
    shutil.copytree(migrate.BACKEND / "migrations", scripts, ignore=shutil.ignore_patterns("__pycache__"))
    head = migrate.head_revision()  # 练习迁移接在当前最新版本后面
    (scripts / "versions" / "zz_practice.py").write_text(EXTRA.replace("{head}", head), encoding="utf-8")
    cfg = migrate.alembic_config(scripts)

    migrate.upgrade(engine)  # 正式迁移 → 最新版本
    with engine.begin() as c:
        _seed(c)

    migrate.upgrade(engine, cfg)  # → 练习版本
    with engine.connect() as c:
        assert migrate.current_revision(c) == "practice"
        cols = {x["name"] for x in inspect(c).get_columns("workers")}
        assert {"phone", "shift_note"} <= cols
        assert c.execute(text("SELECT name, shift_note FROM workers")).one() == ("Petar", "n/a")
        assert c.execute(text("SELECT content_zh FROM tasks")).scalar() == "检查球磨机"
        assert c.execute(text("SELECT count(*) FROM task_workers")).scalar() == 1
        assert c.execute(text("SELECT count(*) FROM audit_log")).scalar() == 1
        with pytest.raises(DBAPIError):  # 留痕表仍然只能追加
            c.execute(text("DELETE FROM audit_log"))
        c.rollback()

    with engine.begin() as c:  # 退回上一版
        cfg.attributes["connection"] = c
        command.downgrade(cfg, head)
    with engine.connect() as c:
        assert migrate.current_revision(c) == head
        assert "phone" not in {x["name"] for x in inspect(c).get_columns("workers")}
        assert c.execute(text("SELECT name FROM workers")).scalar() == "Petar"
        assert c.execute(text("SELECT count(*) FROM task_workers")).scalar() == 1


def test_legacy_database_adopted_when_identical(engine):
    """以前用 create_all 建的库（没有版本记录）：结构一致就直接认领为最新版本。"""
    Base.metadata.create_all(engine)
    with engine.begin() as c:
        _seed(c)
    migrate.upgrade(engine)
    with engine.connect() as c:
        assert migrate.current_revision(c) == migrate.head_revision()
        assert c.execute(text("SELECT count(*) FROM tasks")).scalar() == 1


def test_legacy_database_refused_when_different(engine):
    Base.metadata.create_all(engine)
    with engine.begin() as c:
        c.execute(text("ALTER TABLE holidays DROP COLUMN kind"))
    with pytest.raises(migrate.SchemaMismatch) as e:
        migrate.upgrade(engine)
    assert "holidays" in str(e.value)


def test_0009_converts_old_teams(engine):
    """0009：原来的「倒班 offset + 基准日」「常白班」转换成循环设置，排班结果完全不变；员工补第一条班组记录。"""
    from datetime import date, timedelta

    from app.schedule_service import team_info
    from app.models import Team
    from app.shifts import Schedule, day_team, rotating
    from sqlalchemy.orm import Session

    cfg = migrate.alembic_config()
    with engine.begin() as c:
        cfg.attributes["connection"] = c
        command.upgrade(cfg, "0008")
        c.execute(text("INSERT INTO shift_config (id, base_date, day_start, middle_start, night_start) "
                       "VALUES (1, '2026-11-01', '07:00:00', '15:00:00', '23:00:00')"))
        for i, (code, kind, off) in enumerate([("T1", "rotating", 4), ("T2", "rotating", 6), ("T3", "rotating", 0),
                                               ("T4", "rotating", 2), ("DAY", "day", None), ("X6", "manual", None)], 1):
            c.execute(text("INSERT INTO teams (id, code, name_zh, name_sr, name_en, kind, cycle_offset, sort_order) "
                           "VALUES (:i, :c, :c, :c, :c, :k, :o, :i)"), {"i": i, "c": code, "k": kind, "o": off})
        c.execute(text("INSERT INTO workers (id, name, team_id, is_active, created_at, extra) "
                       "VALUES (1, 'Petar', 2, true, CURRENT_TIMESTAMP, '{}')"))
    migrate.upgrade(engine)
    with Session(engine) as db:
        teams = {t.code: team_info(t) for t in db.query(Team).order_by(Team.id)}
        assert [t.is_main for t in teams.values()] == [True, True, True, True, False, False]
        assert teams["X6"].cycle is None
        new = Schedule(teams=tuple(teams.values()))
        old = Schedule(teams=(rotating(1, 4), rotating(2, 6), rotating(3, 0), rotating(4, 2), day_team(5)))
        for n in range(-30, 400):
            d = date(2026, 11, 1) + timedelta(days=n)
            for code, ot in zip(["T1", "T2", "T3", "T4", "DAY"], old.teams):
                assert new.shift_of(teams[code], d) == old.shift_of(ot, d), (code, d)
        row = db.execute(text("SELECT worker_id, effective_from, team_id FROM worker_schedules")).one()
        assert row[0] == 1 and str(row[1]) == "2000-01-01" and row[2] == 2


def test_0017_departments(engine):
    """0017：已有的班组、员工都归默认车间；角色里的「全部」改成「本车间」，加新权限；退回去也能恢复。"""
    import json

    cfg = migrate.alembic_config()
    with engine.begin() as c:
        cfg.attributes["connection"] = c
        command.upgrade(cfg, "0016")
        c.execute(text("INSERT INTO teams (id, code, name_zh, name_sr, name_en, kind, pattern, cycle_start, holiday_off, "
                       "is_main, sort_order) VALUES (1, 'T1', '1班', 'S1', 'T1', 'cycle', '[\"day\"]', '2026-11-01', "
                       "false, true, 0)"))
        c.execute(text("INSERT INTO workers (id, name, team_id, is_active, created_at, extra) "
                       "VALUES (1, 'Petar', 1, true, CURRENT_TIMESTAMP, '{}')"))
        c.execute(text("INSERT INTO workers (id, name, team_id, is_active, created_at, extra) "
                       "VALUES (2, 'Ana', NULL, true, CURRENT_TIMESTAMP, '{}')"))
    migrate.upgrade(engine)
    with engine.connect() as c:
        assert c.execute(text("SELECT id, code FROM departments")).all() == [(1, "D1")]
        assert c.execute(text("SELECT department_id FROM teams")).scalar() == 1
        assert {r[0] for r in c.execute(text("SELECT department_id FROM workers"))} == {1}
        perms = c.execute(text("SELECT permissions FROM roles WHERE code = 'leader'")).scalar()
        perms = json.loads(perms) if isinstance(perms, str) else perms
        assert perms["task.view"] == "dept" and perms["task.create"] == "team" and perms["worker.manage"] == "none"
    with engine.begin() as c:
        cfg.attributes["connection"] = c
        command.downgrade(cfg, "0016")
    with engine.connect() as c:
        perms = c.execute(text("SELECT permissions FROM roles WHERE code = 'leader'")).scalar()
        perms = json.loads(perms) if isinstance(perms, str) else perms
        assert perms["task.view"] == "all" and "worker.manage" not in perms
        assert "department_id" not in {x["name"] for x in inspect(c).get_columns("teams")}


def test_0022_night_on_end_day(engine):
    """0022：夜班改为记在下班那天。按旧规则和新规则算出的实际上班时间完全一样；夜班的出勤、加班挪到下一天；
    前一晚上了夜班、休息日记的请假去掉（新规则下这天就是那个夜班）。"""
    from datetime import date, datetime, time, timedelta

    from app.schedule_service import _load_base
    from sqlalchemy.orm import Session

    cfg = migrate.alembic_config()
    with engine.begin() as c:
        cfg.attributes["connection"] = c
        command.upgrade(cfg, "0021")
        c.execute(text("INSERT INTO shift_config (id, day_start, middle_start, night_start) "
                       "VALUES (1, '07:00:00', '15:00:00', '23:00:00')"))
        teams = [(1, '["day","day","middle","middle","night","night","off","off"]', "2026-10-28", "cycle"),
                 (2, '["07:00-12:00,23:00-03:00","off","night"]', "2026-11-01", "cycle"),
                 (3, None, None, "manual")]
        for tid, pat, start, kind in teams:
            c.execute(text("INSERT INTO teams (id, department_id, code, name_zh, name_sr, name_en, kind, pattern, "
                           "cycle_start, holiday_off, is_main, sort_order) VALUES (:i, 1, :c, :c, :c, :c, :k, :p, :s, "
                           "false, true, :i)"), {"i": tid, "c": f"T{tid}", "k": kind, "p": pat, "s": start})
        c.execute(text("INSERT INTO users (id, username, password_hash, full_name, role, lang, is_active, created_at, "
                       "failed_logins, must_change_password) VALUES (1, 'admin', 'x', 'A', 'admin', 'zh', true, "
                       "CURRENT_TIMESTAMP, 0, false)"))
        for d, k in (("2026-11-10", "night"), ("2026-11-11", "day")):  # 不固定班组：一个夜班接一个白班
            c.execute(text("INSERT INTO team_shift_overrides (team_id, day, shift_kind, hours, note, created_by, "
                           "created_at) VALUES (3, :d, :k, NULL, 'x', 1, CURRENT_TIMESTAMP)"), {"d": d, "k": k})
        c.execute(text("INSERT INTO workers (id, name, team_id, is_active, created_at, extra, department_id) "
                       "VALUES (1, 'Petar', 1, true, CURRENT_TIMESTAMP, '{}', 1)"))
        c.execute(text("INSERT INTO worker_schedules (worker_id, effective_from, team_id, pattern, holiday_off, note, "
                       "created_at) VALUES (1, '2000-01-01', 1, NULL, false, '', CURRENT_TIMESTAMP)"))
        # 1 班 11-01 夜班（旧规则 11-01 23:00 开始）：病假；11-02 夜班上了；11-03 休息日记了请假；11-04 休息日病假
        for d, st in (("2026-11-01", "sick"), ("2026-11-03", "leave"), ("2026-11-04", "sick")):
            c.execute(text("INSERT INTO attendance (worker_id, day, status, shift_kind, team_id, note, source, "
                           "updated_by, updated_at) VALUES (1, :d, :s, NULL, NULL, '', 'manual', 1, CURRENT_TIMESTAMP)"),
                      {"d": d, "s": st})
        c.execute(text("INSERT INTO overtime (day, shift_kind, worker_id, team_id, until, note, created_by, created_at) "
                       "VALUES ('2026-11-02', 'night', 1, NULL, '2026-11-03 06:00:00+00', '', 1, CURRENT_TIMESTAMP)"))

    def old_windows(entry, d):  # 旧规则：夜班从当天 23:00 开始，凌晨开始的段在第二天
        t = {"day": ("07:00", "15:00"), "middle": ("15:00", "23:00"), "night": ("23:00", "07:00")}
        segs = [t[entry]] if entry in t else [] if entry == "off" else [tuple(x.split("-")) for x in entry.split(",")]
        out = set()
        for a, b in segs:
            st = datetime.combine(d, time.fromisoformat(a))
            if st.time() < time(7):
                st += timedelta(days=1)
            en = datetime.combine(st.date(), time.fromisoformat(b))
            if en <= st:
                en += timedelta(days=1)
            out.add((st, en))
        return out

    old_pat = {1: ["day", "day", "middle", "middle", "night", "night", "off", "off"],
               2: ["07:00-12:00,23:00-03:00", "off", "night"]}
    old_start = {1: date(2026, 10, 28), 2: date(2026, 11, 1)}
    old_ovr = {date(2026, 11, 10): "night", date(2026, 11, 11): "day"}

    def old_entry(tid, d):
        if tid == 3:
            return old_ovr.get(d, "off")
        return old_pat[tid][(d - old_start[tid]).days % len(old_pat[tid])]

    migrate.upgrade(engine)
    with Session(engine) as db:
        sched = _load_base(db)
        for tid in (1, 2, 3):
            team = sched.team(tid)
            old, new = set(), set()
            for n in range(-5, 40):
                d = date(2026, 11, 1) + timedelta(days=n)
                old |= old_windows(old_entry(tid, d), d)
                new |= set(sched.entry_hours(sched.team_entry(team, d), d))
            lo, hi = datetime(2026, 11, 1), datetime(2026, 12, 1)
            assert {w for w in old if lo <= w[0] < hi} == {w for w in new if lo <= w[0] < hi}, tid
        assert sched.teams[0].cycle.pattern == ("day", "day", "middle", "middle", "off", "night", "night", "off")
        rows = db.execute(text("SELECT day, status FROM attendance ORDER BY day")).all()
        # 11-01 夜班病假 → 11-02；11-03 的请假去掉（11-03 的班 = 11-02 晚上上过的夜班）；11-04 不动
        assert [(str(d), s) for d, s in rows] == [("2026-11-02", "sick"), ("2026-11-04", "sick")]
        assert str(db.execute(text("SELECT day FROM overtime")).scalar()) == "2026-11-03"
    with engine.begin() as c:  # 退回去：循环恢复
        cfg.attributes["connection"] = c
        command.downgrade(cfg, "0021")
    with engine.connect() as c:
        p = c.execute(text("SELECT pattern FROM teams WHERE id = 1")).scalar()
        import json
        assert (json.loads(p) if isinstance(p, str) else p) == old_pat[1]


def test_alembic_ini_is_ascii():
    """中文 Windows 上 Alembic 按 GBK 读 alembic.ini，里面不能有非 ASCII 字符（2026-11-23 实际踩到）。"""
    data = (migrate.BACKEND / "alembic.ini").read_bytes()
    assert all(b < 128 for b in data)


def test_0021_schedule_why(engine):
    """0021：角色加「看排班原因」权限，按以前的规则给默认值（班长等 → 本车间，成员 → 不能）；退回去也能去掉。"""
    import json

    cfg = migrate.alembic_config()
    with engine.begin() as c:
        cfg.attributes["connection"] = c
        command.upgrade(cfg, "0020")
    migrate.upgrade(engine)

    def perms(c, code):
        p = c.execute(text("SELECT permissions FROM roles WHERE code = :c"), {"c": code}).scalar()
        return json.loads(p) if isinstance(p, str) else p

    with engine.connect() as c:
        assert perms(c, "leader")["schedule.why"] == "dept"
        assert perms(c, "member")["schedule.why"] == "none"
    with engine.begin() as c:
        cfg.attributes["connection"] = c
        command.downgrade(cfg, "0020")
    with engine.connect() as c:
        assert "schedule.why" not in perms(c, "leader")
