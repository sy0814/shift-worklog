"""数据库迁移：启动时把数据库结构升级到最新版本（Alembic）。

- 新数据库：从第一版开始依次执行所有迁移
- 已有版本记录的数据库：只执行还没执行过的迁移，数据保留
- 用旧方式（create_all）建的、没有版本记录的数据库：先核对结构和当前代码完全一致才「认领」，
  否则拒绝启动并列出差异，避免在不明状态上继续升级
"""

import logging
from pathlib import Path

from alembic import command
from alembic.autogenerate import compare_metadata
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import inspect
from sqlalchemy.engine import Connection, Engine

from .db import Base

log = logging.getLogger("migrate")
BACKEND = Path(__file__).resolve().parent.parent


class SchemaMismatch(RuntimeError):
    pass


def alembic_config(script_location: Path | None = None) -> Config:
    cfg = Config(str(BACKEND / "alembic.ini"))
    cfg.set_main_option("script_location", str(script_location or BACKEND / "migrations"))
    return cfg


def head_revision(cfg: Config | None = None) -> str:
    return ScriptDirectory.from_config(cfg or alembic_config()).get_current_head()


def current_revision(conn: Connection) -> str | None:
    return MigrationContext.configure(conn).get_current_revision()


def schema_diff(conn: Connection) -> list:
    """数据库实际结构和代码（app/models.py）的差异；空列表 = 一致。"""
    from . import models  # noqa: F401

    ctx = MigrationContext.configure(conn, opts={"compare_type": True})
    return compare_metadata(ctx, Base.metadata)


def upgrade(engine: Engine, cfg: Config | None = None) -> None:
    cfg = cfg or alembic_config()
    with engine.begin() as conn:
        tables = set(inspect(conn).get_table_names())
        if "alembic_version" not in tables and "users" in tables:
            diffs = schema_diff(conn)
            if diffs:
                raise SchemaMismatch(
                    "数据库是旧方式建的，结构和当前程序不一致，不能自动升级。差异：\n"
                    + "\n".join(f"  {d}" for d in diffs[:30])
                )
            log.warning("旧方式建的数据库，结构与当前版本一致，标记为版本 %s", head_revision(cfg))
            cfg.attributes["connection"] = conn
            command.stamp(cfg, "head")
            return
        before = current_revision(conn)
        cfg.attributes["connection"] = conn
        command.upgrade(cfg, "head")
        after = current_revision(conn)
        if before != after:
            log.warning("数据库已升级：%s → %s", before or "（空库）", after)
