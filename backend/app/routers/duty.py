"""首页：当前 / 下一个班次的在岗人员和状态。"""

from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import attendance_service as att, permissions
from ..config import get_settings
from ..db import get_db
from ..models import Role, Task, User, Worker
from ..overtime_service import expand as expand_overtime
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
    team_id: int | None = None  # 这个班次在哪个班组上（支援的人是被支援的班组）
    role_id: int | None = None
    status: str  # busy（手上有未完成的任务：未开始或进行中）/ idle（空闲）/ leave / sick / absent / off（本该上班但请假等）
    #            / off_hours（有自定义上班时间，现在不在上班时间里，例如午休）
    support: bool  # 是不是从其他班组来支援的
    tasks: list[DutyTask]
    overtime_until: datetime | None = None  # 加班到几点（本地时间）
    overtime_prev: bool = False  # 上一个班留下来加班的
    hours: str | None = None  # 自定义上班时间，例如 "07:00-12:00,14:00-17:00"


class DutyTeam(BaseModel):
    team_id: int
    workers: list[DutyWorker]


class DutyCounts(BaseModel):
    on_duty: int
    busy: int
    idle: int
    absent: int
    off_hours: int = 0


class DutyOut(BaseModel):
    which: str
    shift_date: date
    shift_kind: str
    start: datetime
    end: datetime
    main_team_id: int | None  # 卡片上显示的班组（倒班班组）
    top: list[DutyWorker] = []  # 「首页单独显示」的角色（班长、副班长……），单独列在上面
    teams: list[DutyTeam]  # 这个班次所有在岗班组（含常白班），不含 top 里的人
    counts: DutyCounts
    can_add: bool  # 当前用户能不能在这里快捷添加任务


def _status_order(s: str) -> int:
    return {"busy": 0, "idle": 1, "off_hours": 2}.get(s, 3)


def _in_hours(sched, hours: str, d, now) -> bool:
    return any(a <= now < b for a, b in sched.entry_hours(hours, d))


def _working_now(sched, row: dict, d, now):
    """有自定义上班时间、而且现在正在时间段里的那一天的出勤（看当天和前一天）；没有返回 None。"""
    for day in (d, d - timedelta(days=1)):
        a = row.get(day)
        if a is not None and a.status == "present" and a.hours and _in_hours(sched, a.hours, day, now):
            return a
    return None


@router.get("/duty", response_model=DutyOut)
def duty(which: str = Query(default="current", pattern="^(current|next)$"), db: Session = Depends(get_db),
         user: User = Depends(get_current_user)):
    """某个班次在岗的人：按出勤（含调班、顶班）算；忙碌 = 手上有未完成的任务（未开始或进行中）。"""
    sched = load_schedule(db)
    d, k = sched.shift_at(local_now())
    if which == "next":
        d, k = sched.next_shift(d, k)
    start, end = sched.shift_window(d, k)
    slot_teams = sched.teams_on(d, k)
    slot_ids = {t.id for t in slot_teams}
    main = sched.main_team_on(d, k)

    workers = list(db.scalars(select(Worker).where(Worker.is_active.is_(True)).order_by(Worker.name)))
    eff = att.effective(db, workers, d - timedelta(days=1), d)
    rows: dict[int, list[tuple[Worker, str, bool]]] = {}
    hours_of: dict[int, str | None] = {}
    # 加班：本班次的人加班到几点；当前班次还要算上上个班留下来加班、还没到点的人
    now = local_now()
    pd, pk = sched.prev_shift(d, k)
    ot: dict[int, tuple[datetime, bool]] = {}
    for x in expand_overtime(db, pd, d, workers):
        if (x.day, x.shift_kind) == (d, k):
            ot[x.worker_id] = (x.until_local, False)
        elif which == "current" and (x.day, x.shift_kind) == (pd, pk) and x.end_local <= now < x.until_local:
            ot.setdefault(x.worker_id, (x.until_local, True))
    prev_eff = att.effective(db, workers, pd, pd) if any(p for _u, p in ot.values()) else {}
    for w in workers:
        if w.id in ot and ot[w.id][1]:
            a = prev_eff[w.id][pd]
            team = a.team_id or w.team_id
            rows.setdefault(team, []).append((w, "on", team != w.team_id))
            continue
        a = eff[w.id][d]
        if a.status == "present" and a.shift_kind == k:
            team = a.team_id or w.team_id
            st = "on"
            if which == "current" and a.hours and not _in_hours(sched, a.hours, d, now):
                st = "off_hours"  # 自定义上班时间：现在不在时间段里（例如午休、还没到点）
            hours_of[w.id] = a.hours
            rows.setdefault(team, []).append((w, st, team != w.team_id))
        elif which == "current" and (x := _working_now(sched, eff[w.id], d, now)) is not None:
            # 自定义上班时间跨过了班次分界（例如白班组 14:00-17:00，16:00 已经是中班时段）：现在在上班，也算在岗
            hours_of[w.id] = x.hours
            team = x.team_id or w.team_id
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

    roles = {r.id: r for r in db.scalars(select(Role))}
    member = next((r.id for r in roles.values() if r.code == "member"), None)
    on_top = lambda w: roles.get(w.role_id or member) is not None and roles[w.role_id or member].show_on_top
    top: list[DutyWorker] = []
    teams, counts = [], {"on_duty": 0, "busy": 0, "idle": 0, "absent": 0, "off_hours": 0}
    order = [t.id for t in sorted(slot_teams, key=lambda t: not t.is_main)]
    order += [tid for tid in rows if tid not in order]
    for tid in order:
        out = []
        for w, st, support in rows.get(tid, []):
            mine = sorted(by_worker.get(w.id, []), key=lambda t: (t.status != "in_progress", t.id))
            if st == "on":
                st = "busy" if mine else "idle"  # 分配了任务（未开始也算）就是忙碌
                counts["on_duty"] += 1
                counts[st] += 1
            elif st == "off_hours":
                counts["off_hours"] += 1
            else:
                counts["absent"] += 1
            (top if on_top(w) else out).append(DutyWorker(
                hours=hours_of.get(w.id),
                worker=WorkerOut.model_validate(w), status=st, support=support, team_id=tid, role_id=w.role_id or member,
                overtime_until=ot[w.id][0].replace(tzinfo=get_settings().tz) if w.id in ot else None,
                overtime_prev=ot.get(w.id, (None, False))[1],
                tasks=[DutyTask(id=t.id, content=Trilingual(zh=t.content_zh, sr=t.content_sr, en=t.content_en),
                                source_lang=t.source_lang, status=t.status, is_lead=t.lead_worker_id == w.id,
                                team_id=t.team_id) for t in mine[:5]]))
        out.sort(key=lambda r: (_status_order(r.status), r.worker.name))
        teams.append(DutyTeam(team_id=tid, workers=out))

    tz = get_settings().tz
    return DutyOut(
        which=which, shift_date=d, shift_kind=k, start=start.replace(tzinfo=tz), end=end.replace(tzinfo=tz),
        main_team_id=main.id if main else None, teams=teams,
        top=sorted(top, key=lambda r: (roles[r.role_id].sort_order if r.role_id in roles else 99, order.index(r.team_id)
                                       if r.team_id in order else 99, r.worker.name)), counts=DutyCounts(**counts),
        can_add=permissions.who(db, user).has("task.create") and (user.role == "admin" or user.team_id in slot_ids),
    )
