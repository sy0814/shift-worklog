"""留痕：写日志的工具函数 + 数据库层禁止修改/删除 audit_log。"""

import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.engine import Connection
from sqlalchemy.orm import Session

from .models import AuditLog


def _norm(v: Any) -> Any:
    # SQLite 读回的时间是 naive（库里统一存 UTC），比较前补上时区
    if isinstance(v, datetime) and v.tzinfo is None:
        return v.replace(tzinfo=timezone.utc)
    return v


def _s(v: Any) -> str | None:
    if v is None:
        return None
    if isinstance(v, str):
        return v
    return json.dumps(v, ensure_ascii=False, default=str)


def log(
    db: Session,
    *,
    user_id: int | None,
    action: str,
    entity: str,
    entity_id: Any,
    field: str | None = None,
    old: Any = None,
    new: Any = None,
    extra: dict | None = None,
) -> None:
    db.add(
        AuditLog(
            user_id=user_id,
            action=action,
            entity=entity,
            entity_id=str(entity_id),
            field=field,
            old_value=_s(old),
            new_value=_s(new),
            extra=extra,
        )
    )


def log_changes(
    db: Session,
    obj: Any,
    changes: dict[str, Any],
    *,
    user_id: int | None,
    entity: str,
    entity_id: Any,
    action: str = "update",
) -> bool:
    """把 changes 里与 obj 当前值不同的字段写入 obj，并逐字段留痕。返回是否有改动。"""
    changed = False
    for field, new in changes.items():
        old = _norm(getattr(obj, field))
        if old == _norm(new):
            continue
        setattr(obj, field, new)
        log(db, user_id=user_id, action=action, entity=entity, entity_id=entity_id,
            field=field, old=old, new=new)
        changed = True
    return changed


_SQLITE_TRIGGERS = [
    """CREATE TRIGGER IF NOT EXISTS audit_log_no_update BEFORE UPDATE ON audit_log
       BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END""",
    """CREATE TRIGGER IF NOT EXISTS audit_log_no_delete BEFORE DELETE ON audit_log
       BEGIN SELECT RAISE(ABORT, 'audit_log is append-only'); END""",
]

_PG_TRIGGERS = [
    """CREATE OR REPLACE FUNCTION audit_log_append_only() RETURNS trigger AS $$
       BEGIN RAISE EXCEPTION 'audit_log is append-only'; END; $$ LANGUAGE plpgsql""",
    "DROP TRIGGER IF EXISTS audit_log_no_change ON audit_log",
    """CREATE TRIGGER audit_log_no_change BEFORE UPDATE OR DELETE ON audit_log
       FOR EACH ROW EXECUTE FUNCTION audit_log_append_only()""",
]


def install_append_only_guard(conn: Connection) -> None:
    stmts = _PG_TRIGGERS if conn.dialect.name == "postgresql" else _SQLITE_TRIGGERS
    for s in stmts:
        conn.execute(text(s))


@event.listens_for(AuditLog.__table__, "after_create")
def _after_create(target, conn, **kw):
    install_append_only_guard(conn)
