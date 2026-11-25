"""「为什么？」：解释某人某天 / 某班组某天的排班结果是怎么来的（见 app/explain.py）。"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import explain, permissions
from ..db import get_db
from ..models import Team, User, Worker
from ..security import get_current_user

router = APIRouter(prefix="/api/explain", tags=["explain"])


WHY_PERMS = ("attendance.edit", "schedule.team_shift", "worker.manage", "team.manage")


def _check(db: Session, user: User) -> None:
    """管理员和能改出勤 / 调班 / 名册 / 班组的人能看；成员看不到（用户 2026-11-26 要求）。前端 auth.canWhy 同一条件。"""
    w = permissions.who(db, user)
    permissions.require(user.role == "admin" or any(w.has(p) for p in WHY_PERMS), "permission denied")


@router.get("/worker/{worker_id}")
def worker_day(worker_id: int, day: date, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _check(db, user)
    w = db.get(Worker, worker_id)
    if w is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return explain.worker_day(db, w, day)


@router.get("/team/{team_id}")
def team_day(team_id: int, day: date, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _check(db, user)
    t = db.get(Team, team_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return explain.team_day(db, t, day)
