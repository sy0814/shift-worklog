"""车间（部门）：班组之上的一层。

- 每个班组属于一个车间（teams.department_id）；排班的主班组、合并显示、交接顺序、排班检查都只在车间内算（shifts.py）。
- 员工的车间（workers.department_id）：有班组时自动等于班组的车间（下面的 before_flush 同步），没有班组的人单独设。
- 「当前车间」：页面上正在看哪个车间。请求头 X-Department 指定；只有能看全厂的人（系统管理员、task.view 为 all）
  才能切换，其他人永远是自己的车间（current / get_dept）。
- 只有一个车间时，前端不显示车间，和以前完全一样。
"""

from fastapi import Depends, Request
from sqlalchemy import event, select
from sqlalchemy.orm import Session

from .db import get_db
from .models import Department, Team, User, Worker
from .security import get_current_user


@event.listens_for(Session, "before_flush")
def _sync_worker_department(session: Session, _ctx, _instances) -> None:
    """员工换了班组 → 车间跟着班组走。"""
    for obj in list(session.new) + list(session.dirty):
        if isinstance(obj, Worker) and obj.team_id is not None:
            with session.no_autoflush:
                team = session.get(Team, obj.team_id)
            if team is not None and obj.department_id != team.department_id:
                obj.department_id = team.department_id


def all_departments(db: Session, active_only: bool = False) -> list[Department]:
    q = select(Department).order_by(Department.sort_order, Department.id)
    if active_only:
        q = q.where(Department.is_active.is_(True))
    return list(db.scalars(q))


def default_id(db: Session) -> int | None:
    d = all_departments(db, active_only=True) or all_departments(db)
    return d[0].id if d else None


def team_ids(db: Session, dept_id: int | None) -> set[int]:
    if dept_id is None:
        return set()
    return set(db.scalars(select(Team.id).where(Team.department_id == dept_id)))


def dept_of_team(db: Session, team_id: int | None) -> int | None:
    return db.scalar(select(Team.department_id).where(Team.id == team_id)) if team_id else None


def dept_of_user(db: Session, user: User) -> int | None:
    """账号自己的车间：名册里的车间；没有就按账号的班组。系统管理员为 None。"""
    if user.role == "admin":
        return None
    if user.worker_id:
        d = db.scalar(select(Worker.department_id).where(Worker.id == user.worker_id))
        if d is not None:
            return d
    return dept_of_team(db, user.team_id)


def can_switch(db: Session, user: User) -> bool:
    """能不能在各车间之间切换：系统管理员，或者「看任务」范围是全部的角色（例如厂长）。"""
    if user.role == "admin":
        return True
    from . import permissions

    worker = db.get(Worker, user.worker_id) if user.worker_id else None
    role = permissions.role_of(db, worker)
    return bool(role and (role.permissions or {}).get("task.view") == "all")


def current(db: Session, user: User, header: str | None) -> int | None:
    """当前车间：能切换的人按请求头，否则是自己的车间；都没有就用第一个车间。"""
    own = dept_of_user(db, user)
    if header and can_switch(db, user):
        try:
            want = int(header)
        except ValueError:
            want = None
        if want is not None and db.get(Department, want) is not None:
            return want
    return own if own is not None else default_id(db)


def get_dept(request: Request, db: Session = Depends(get_db), user: User = Depends(get_current_user)) -> int | None:
    """FastAPI 依赖：当前车间 id。"""
    return current(db, user, request.headers.get("X-Department"))
