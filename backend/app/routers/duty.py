"""首页：当前 / 下一个班次的在岗人员和状态。"""

from datetime import date, datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import attendance_service as att
from ..config import get_settings
from ..db import get_db
from ..models import Task, User, Worker
from ..schedule_service import load_schedule, local_now
from ..schemas import Trilingual, WorkerOut
from ..security import get_current_user

router = APIRouter(prefix="/api", tags=["duty"])
OPEN = ("not_started", "in_progress")


class DutyTask(BaseModel):
    id: int
    content: Trilingual
    source_lang: str
    status: str
    is_lead: bool
    team_id: int


class DutyWorker(BaseModel):
    worker: WorkerOut
    status: str  # busy（有进行中的任务）/ idle（空闲）/ leave / sick / absent / off（本该上班但请假等）
    support: bool  # 是不是从其他班组来支援的
    tasks: list[DutyTask]


class DutyTeam(BaseModel):
    team_id: int
    workers: list[DutyWorker]


class DutyCounts(BaseModel):
    on_duty: int
    busy: int
    idle: int
    absent: int


class DutyOut(BaseModel):
    which: str
    shift_date: date
    shift_kind: str
    start: datetime
    end: datetime
    main_team_id: int | None  # 卡片上显示的班组（倒班班组）
    teams: list[DutyTeam]  # 这个班次所有在岗班组（含常白班）
    counts: DutyCounts
    can_add: bool  # 当前用户能不能在这里快捷添加任务


def _status_order(s: str) -> int:
    return {"busy": 0, "idle": 1}.get(s, 2)


@router.get("/duty", response_model=DutyOut)
def duty(which: str = Query(default="current", pattern="^(current|next)$"), db: Session = Depends(get_db),
         user: User = Depends(get_current_user)):
    """某个班次在岗的人：按出勤（含调班、顶班）算；忙碌 = 有进行中的任务。"""
    sched = load_schedule(db)
    d, k = sched.shift_at(local_now())
    if which == "next":
        d, k = sched.next_shift(d, k)
    start, end = sched.shift_window(d, k)
    slot_teams = sched.teams_on(d, k)
    slot_ids = {t.id for t in slot_teams}
    main = sched.rotating_team_on(d, k)

    workers = list(db.scalars(select(Worker).where(Worker.is_active.is_(True)).order_by(Worker.name)))
    eff = att.effective(db, workers, d, d)
    rows: dict[int, list[tuple[Worker, str, bool]]] = {}
    for w in workers:
        a = eff[w.id][d]
        if a.status == "present" and a.shift_kind == k:
            team = a.team_id or w.team_id
            rows.setdefault(team, []).append((w, "on", team != w.team_id))
        elif w.team_id in slot_ids and a.status in ("leave", "sick", "absent", "off") and a.source != "default":
            rows.setdefault(w.team_id, []).append((w, a.status, False))  # 本该上这个班，但请假 / 调走了

    ids = [w.id for rs in rows.values() for w, _s, _x in rs]
    tasks = list(db.scalars(select(Task).options(selectinload(Task.workers))
                            .where(Task.status.in_(OPEN), Task.workers.any(Worker.id.in_(ids))))) if ids else []
    by_worker: dict[int, list[Task]] = {}
    for t in tasks:
        for w in t.workers:
            by_worker.setdefault(w.id, []).append(t)

    teams, counts = [], {"on_duty": 0, "busy": 0, "idle": 0, "absent": 0}
    order = [t.id for t in sorted(slot_teams, key=lambda t: t.kind != "rotating")]
    order += [tid for tid in rows if tid not in order]
    for tid in order:
        out = []
        for w, st, support in rows.get(tid, []):
            mine = sorted(by_worker.get(w.id, []), key=lambda t: (t.status != "in_progress", t.id))
            if st == "on":
                st = "busy" if any(t.status == "in_progress" for t in mine) else "idle"
                counts["on_duty"] += 1
                counts[st] += 1
            else:
                counts["absent"] += 1
            out.append(DutyWorker(
                worker=WorkerOut.model_validate(w), status=st, support=support,
                tasks=[DutyTask(id=t.id, content=Trilingual(zh=t.content_zh, sr=t.content_sr, en=t.content_en),
                                source_lang=t.source_lang, status=t.status, is_lead=t.lead_worker_id == w.id,
                                team_id=t.team_id) for t in mine[:5]]))
        out.sort(key=lambda r: (_status_order(r.status), r.worker.name))
        teams.append(DutyTeam(team_id=tid, workers=out))

    tz = get_settings().tz
    return DutyOut(
        which=which, shift_date=d, shift_kind=k, start=start.replace(tzinfo=tz), end=end.replace(tzinfo=tz),
        main_team_id=main.id if main else None, teams=teams, counts=DutyCounts(**counts),
        can_add=user.role == "admin" or (user.team_id in slot_ids),
    )
