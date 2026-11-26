"""「为什么？」：解释某人某天 / 某班组某天的排班结果是怎么来的（见 app/explain.py）。"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import explain, permissions
from ..db import get_db
from ..models import Team, User, Worker
from ..security import get_current_user

router = APIRouter(prefix="/api/explain", tags=["explain"])


# 权限 schedule.why（角色权限页「看排班原因」）：本班组 / 本车间 / 全厂；成员默认不能（用户 2026-11-26 要求）
def _check_team(db: Session, user: User, team_id: int | None, dept_id: int | None = None) -> None:
    w = permissions.who(db, user)
    ok = w.team_ok("schedule.why", team_id) if team_id is not None else w.dept_ok("schedule.why", dept_id)
    permissions.require(ok, "permission denied")


@router.get("/worker/{worker_id}")
def worker_day(worker_id: int, day: date, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    w = db.get(Worker, worker_id)
    if w is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    _check_team(db, user, w.team_id, w.department_id)  # 没有班组的人（例如管理人员）按车间
    return explain.worker_day(db, w, day)


@router.get("/team/{team_id}")
def team_day(team_id: int, day: date, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    t = db.get(Team, team_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    _check_team(db, user, t.id)
    return explain.team_day(db, t, day)
