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

revision = "0002"
down_revision = "0001"
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
    c.execute(text("INSERT INTO teams (id, code, name_zh, name_sr, name_en, kind, cycle_offset, sort_order) "
                   "VALUES (1, 'T1', '1班', 'Smena 1', 'Team 1', 'rotating', 4, 0)"))
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
    (scripts / "versions" / "0002_practice.py").write_text(EXTRA, encoding="utf-8")
    cfg = migrate.alembic_config(scripts)

    migrate.upgrade(engine)  # 正式迁移 → 0001
    with engine.begin() as c:
        _seed(c)

    migrate.upgrade(engine, cfg)  # → 0002
    with engine.connect() as c:
        assert migrate.current_revision(c) == "0002"
        cols = {x["name"] for x in inspect(c).get_columns("workers")}
        assert {"phone", "shift_note"} <= cols
        assert c.execute(text("SELECT name, shift_note FROM workers")).one() == ("Petar", "n/a")
        assert c.execute(text("SELECT content_zh FROM tasks")).scalar() == "检查球磨机"
        assert c.execute(text("SELECT count(*) FROM task_workers")).scalar() == 1
        assert c.execute(text("SELECT count(*) FROM audit_log")).scalar() == 1
        with pytest.raises(DBAPIError):  # 留痕表仍然只能追加
            c.execute(text("DELETE FROM audit_log"))
        c.rollback()

    with engine.begin() as c:  # 退回 0001
        cfg.attributes["connection"] = c
        command.downgrade(cfg, "0001")
    with engine.connect() as c:
        assert migrate.current_revision(c) == "0001"
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
