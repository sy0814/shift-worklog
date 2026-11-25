"""「为什么？」：解释某人某天 / 某班组某天的排班结果是怎么来的（见 app/explain.py）。"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from .. import explain
from ..db import get_db
from ..models import Team, User, Worker
from ..security import get_current_user

router = APIRouter(prefix="/api/explain", tags=["explain"])


# 和出勤表、排班日历一样：登录的人都能看
@router.get("/worker/{worker_id}")
def worker_day(worker_id: int, day: date, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    w = db.get(Worker, worker_id)
    if w is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return explain.worker_day(db, w, day)


@router.get("/team/{team_id}")
def team_day(team_id: int, day: date, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    t = db.get(Team, team_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return explain.team_day(db, t, day)
