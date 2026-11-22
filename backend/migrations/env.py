"""Alembic 环境：数据库地址来自应用配置（backend/.env），表结构来自 app.models。"""

from alembic import context

from app import models  # noqa: F401  注册所有表
from app.config import get_settings
from app.db import Base, make_engine

config = context.config
target_metadata = Base.metadata


def run_migrations_offline() -> None:
    context.configure(url=get_settings().database_url, target_metadata=target_metadata,
                      literal_binds=True, render_as_batch=True, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # 允许调用方（如测试、启动时自动升级）直接传入连接
    connection = config.attributes.get("connection")
    if connection is not None:
        _run(connection)
        return
    engine = make_engine(get_settings().database_url)
    with engine.connect() as conn:
        _run(conn)
        conn.commit()


def _run(connection) -> None:
    # render_as_batch：SQLite 改表要「建新表→复制→改名」，batch 模式自动处理；PostgreSQL 不受影响
    sqlite = connection.dialect.name == "sqlite"
    if sqlite:
        # 重建被引用的表时外键检查会拦住，迁移期间先关掉，结束后检查完整性再打开
        connection.exec_driver_sql("PRAGMA foreign_keys=OFF")
    context.configure(connection=connection, target_metadata=target_metadata,
                      render_as_batch=True, compare_type=True)
    try:
        with context.begin_transaction():
            context.run_migrations()
        if sqlite:
            bad = connection.exec_driver_sql("PRAGMA foreign_key_check").fetchall()
            if bad:
                raise RuntimeError(f"迁移后外键不一致：{bad[:10]}")
    finally:
        if sqlite:
            connection.exec_driver_sql("PRAGMA foreign_keys=ON")


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
