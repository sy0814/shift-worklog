"""某个员工 / 账号有没有被用过（能不能删除）。

按数据库里所有指向 workers.id / users.id 的外键去数（以后加了新表也自动算上），再加上存在 JSON 里的引用
（定期巡查的固定人员、小项目指派）。用过的人只能停用（名册「在职」关掉、账号停用），不能删除：
任务、出勤、操作记录里都有他，操作记录只能追加不能改删。
"""

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .db import Base
from .models import InspectionTemplate


def _refs(db: Session, target: str, ident: int, skip: set[tuple[str, str]]) -> dict[str, int]:
    """{表名: 行数}：所有外键指向 target（例如 "workers.id"）且等于 ident 的行。"""
    out: dict[str, int] = {}
    for table in Base.metadata.sorted_tables:
        for col in table.columns:
            if (table.name, col.name) in skip:
                continue
            if any(fk.target_fullname == target for fk in col.foreign_keys):
                n = db.scalar(select(func.count()).select_from(table).where(col == ident)) or 0
                if n:
                    out[table.name] = out.get(table.name, 0) + n
    return out


def worker_refs(db: Session, worker_id: int) -> dict[str, int]:
    """员工被用过的地方（不算他自己的排班记录和账号，那些删员工时一起删）。"""
    out = _refs(db, "workers.id", worker_id, {("worker_schedules", "worker_id"), ("users", "worker_id")})
    n = 0
    for t in db.scalars(select(InspectionTemplate)):
        if worker_id in (t.worker_ids or []) or any((s or {}).get("worker_id") == worker_id for s in (t.sub_items or [])):
            n += 1
    if n:
        out["inspection_templates"] = n
    return out


def user_refs(db: Session, user_id: int) -> dict[str, int]:
    """账号被用过的地方（登录、录入、修改……都会留下记录）。"""
    return _refs(db, "users.id", user_id, set())
