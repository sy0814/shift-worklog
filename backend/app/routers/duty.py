"""首页：当前 / 下一个班次的在岗人员和状态。"""

from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import attendance_service as att, permissions, work_hours
from ..config import get_settings
from ..db import get_db
from ..models import Role, Task, User, Worker
from ..overtime_service import expand as expand_overtime
from ..schedule_service import load_schedule, local_now
from ..departments import get_dept
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
    #  算在别的班、但自定义上班时间有一段落在这个班次里的人（例如白班 07-12、14-17 的人在中班的前两小时）也列出来，
    #  照常算忙碌 / 空闲、计入在岗，另外给出 overlap_from / overlap_until（到几点）
    support: bool  # 是不是从其他班组来支援的
    tasks: list[DutyTask]
    overtime_until: datetime | None = None  # 加班到几点（本地时间）
    overtime_prev: bool = False  # 上一个班留下来加班的
    hours: str | None = None  # 自定义上班时间，例如 "07:00-12:00,14:00-17:00"
    # 不在上班时间（off_hours）时：下一段几点开始（午休后回来 / 还没到点）；为空 = 今天的时间段都结束了
    back_at: datetime | None = None
    overlap_from: datetime | None = None  # overlap：在这个班次里从几点到几点还在上班（本地时间）
    overlap_until: datetime | None = None


class DutyTeam(BaseModel):
    team_id: int
    workers: list[DutyWorker]


class DutyCounts(BaseModel):
    managers: int = 0  # 管理人员在班（忙碌 + 空闲）；下面 on_duty 起不含管理人员
    managers_busy: int = 0
    managers_idle: int = 0
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
    # 管理人员：能给整个车间派活的人（角色的「新建任务」范围是本车间 / 全厂，例如车间管理员），本车间的、这个班次在班的。
    # 他们一般不属于班组，按自己的个人排班（名册「长期排班」）算在不在班；不在班组列表里，单独一块（2026-11-26 用户要求）
    managers: list[DutyWorker] = []
    managers_unscheduled: list[str] = []  # 本车间还没设排班（没有班组也没有个人循环）的管理人员，没法判断在不在班
    top: list[DutyWorker] = []  # 「首页单独显示」的角色（班长、副班长……），单独列在上面
    teams: list[DutyTeam]  # 这个班次所有在岗班组（含常白班），不含 top、managers 里的人
    counts: DutyCounts
    can_add: bool  # 当前用户能不能在这里快捷添加任务


def _status_order(s: str) -> int:
    return {"busy": 0, "idle": 1, "off_hours": 2}.get(s, 3)


@dataclass
class _Slot:
    """要看的那个班次。which = current（当前班次，看「现在」）/ next（下一个接班）。"""
    sched: object
    which: str
    d: date
    k: str
    start: datetime
    end: datetime
    now: datetime

    @property
    def current(self) -> bool:
        return self.which == "current"


@dataclass
class _Placed:
    """每个人放在哪个班组、什么状态（on / off_hours / leave……），以及自定义上班时间带来的附加信息。"""
    rows: dict = field(default_factory=dict)  # 班组 id → [(员工, 状态, 是否支援)]
    hours: dict = field(default_factory=dict)  # 员工 id → 自定义上班时间
    back: dict = field(default_factory=dict)  # 员工 id → 午休后几点回来
    overlap: dict = field(default_factory=dict)  # 员工 id → (从, 到)：算在别的班、这段时间落在本班次

    def add(self, team_id, w: Worker, status: str, support: bool) -> None:
        self.rows.setdefault(team_id, []).append((w, status, support))


def _overtime(db: Session, slot: _Slot, workers: list[Worker]) -> dict[int, tuple[datetime, bool]]:
    """员工 id → (加班到几点, 是不是上个班留下来的)。当前班次还要算上个班留下来、还没到点的人。"""
    pd, pk = slot.sched.prev_shift(slot.d, slot.k)
    ot: dict[int, tuple[datetime, bool]] = {}
    for x in expand_overtime(db, pd, slot.d, workers):
        if (x.day, x.shift_kind) == (slot.d, slot.k):
            ot[x.worker_id] = (x.until_local, False)
        elif slot.current and (x.day, x.shift_kind) == (pd, pk) and x.end_local <= slot.now < x.until_local:
            ot.setdefault(x.worker_id, (x.until_local, True))
    return ot


def _place(db: Session, slot: _Slot, workers: list[Worker], eff: dict, ot: dict, slot_ids: set) -> _Placed:
    """按出勤把每个人放进这个班次的班组（顶班、支援的放进被支援的班组），不在这个班的不放。"""
    sched, d, k, now = slot.sched, slot.d, slot.k, slot.now
    out = _Placed()
    pd, _pk = sched.prev_shift(d, k)
    prev_eff = att.effective(db, workers, pd, pd) if any(p for _u, p in ot.values()) else {}
    for w in workers:
        if w.id in ot and ot[w.id][1]:  # 上个班留下来加班
            a = prev_eff[w.id][pd]
            team = a.team_id or w.team_id
            out.add(team, w, "on", team != w.team_id)
            continue
        a = eff[w.id][d]
        if a.status == "present" and a.shift_kind == k:
            team = a.team_id or w.team_id
            st = "on"
            if slot.current and a.hours and not work_hours.in_hours(sched, a.hours, d, now):
                st = "off_hours"  # 自定义上班时间：现在不在时间段里（例如午休、还没到点）
                if (nx := work_hours.next_start(sched, a.hours, d, now)) is not None:
                    out.back[w.id] = nx
            out.hours[w.id] = a.hours
            out.add(team, w, st, team != w.team_id)
        elif slot.current and (x := work_hours.working_now(sched, eff[w.id], d, now)) is not None:
            # 自定义上班时间跨过了班次分界（例如白班组 14:00-17:00，16:00 已经是中班时段）：现在在上班，也算在岗
            out.hours[w.id] = x.hours
            team = x.team_id or w.team_id
            out.add(team, w, "on", team != w.team_id)
        elif w.team_id in slot_ids and a.status in ("leave", "sick", "absent", "off") and a.source != "default":
            out.add(w.team_id, w, a.status, False)  # 本该上这个班，但请假 / 调走了
        elif (x := work_hours.overlap(sched, eff[w.id], d, k, slot.start, slot.end,
                                      now if slot.current else None)) is not None:
            # 算在别的班（例如白班 07-12、14-17），但有一段时间落在这个班次里：也列出来、计入在岗，写明到几点
            a2, ov_from, ov_until = x
            team = a2.team_id or w.team_id
            out.hours[w.id] = a2.hours
            out.overlap[w.id] = (ov_from, ov_until)
            out.add(team, w, "on", team != w.team_id)
    return out


def _open_tasks(db: Session, ids: list[int]) -> dict[int, list[Task]]:
    """员工 id → 手上未完成的任务（未开始也算，进行中的排前面）。"""
    tasks = list(db.scalars(select(Task).options(selectinload(Task.workers))
                            .where(Task.status.in_(OPEN), Task.workers.any(Worker.id.in_(ids))))) if ids else []
    out: dict[int, list[Task]] = {}
    for t in tasks:
        for w in t.workers:
            out.setdefault(w.id, []).append(t)
    for lst in out.values():
        lst.sort(key=lambda t: (t.status != "in_progress", t.id))
    return out


def _local(dt: datetime | None) -> datetime | None:
    return dt.replace(tzinfo=get_settings().tz) if dt is not None else None


def _row(w: Worker, st: str, support: bool, tid, placed: _Placed, ot: dict, mine: list[Task],
         member_role: int | None) -> DutyWorker:
    """首页人员状态里的一行。在班的：手上有任务（未开始也算）= 忙碌，否则空闲。"""
    if st == "on":
        st = "busy" if mine else "idle"
    ov = placed.overlap.get(w.id, (None, None))
    return DutyWorker(
        worker=WorkerOut.model_validate(w), status=st, support=support, team_id=tid, role_id=w.role_id or member_role,
        hours=placed.hours.get(w.id), back_at=_local(placed.back.get(w.id)), overlap_from=_local(ov[0]),
        overlap_until=_local(ov[1]), overtime_until=_local(ot[w.id][0]) if w.id in ot else None,
        overtime_prev=ot.get(w.id, (None, False))[1],
        tasks=[DutyTask(id=t.id, content=Trilingual(zh=t.content_zh, sr=t.content_sr, en=t.content_en),
                        source_lang=t.source_lang, status=t.status, is_lead=t.lead_worker_id == w.id,
                        team_id=t.team_id) for t in mine[:5]])


def _can_add(db: Session, user: User, slot_ids: set) -> bool:
    """能不能在首页这个班次快捷添加任务。"""
    w = permissions.who(db, user)
    return w.has("task.create") and (w.is_admin or w.scope("task.create") in ("dept", "all")
                                     and any(w.team_ok("task.create", t) for t in slot_ids)
                                     or user.team_id in slot_ids)


@router.get("/duty", response_model=DutyOut)
def duty(which: str = Query(default="current", pattern="^(current|next)$"), db: Session = Depends(get_db),
         user: User = Depends(get_current_user), dept: int | None = Depends(get_dept)):
    """当前车间某个班次在岗的人：按出勤（含调班、顶班）算；忙碌 = 手上有未完成的任务（未开始或进行中）。
    别的车间借调来支援本车间班组的人也算在内（按他顶的班组）。管理人员（能给全车间派活的人）单独一块；
    「首页单独显示」的角色（班长等）列在最上面。"""
    sched = load_schedule(db)
    now = local_now()
    d, k = sched.shift_at(now)
    if which == "next":
        d, k = sched.next_shift(d, k)
    start, end = sched.shift_window(d, k)
    slot = _Slot(sched, which, d, k, start, end, now)
    slot_teams = sched.teams_on(d, k, dept)
    slot_ids = {t.id for t in slot_teams}
    main = sched.main_team_on(d, k, dept)
    dept_ids = {t.id for t in sched.teams if t.dept == dept}

    workers = list(db.scalars(select(Worker).where(Worker.is_active.is_(True)).order_by(Worker.name)))
    roles = {r.id: r for r in db.scalars(select(Role))}
    member = next((r.id for r in roles.values() if r.code == "member"), None)
    role_of = lambda w: roles.get(w.role_id or member)
    is_mgr = lambda w: (role_of(w) is not None and (role_of(w).permissions or {}).get("task.create") in ("dept", "all")
                        and (dept is None or w.department_id == dept))
    on_top = lambda w: role_of(w) is not None and role_of(w).show_on_top

    eff = att.effective(db, workers, d - timedelta(days=1), d + timedelta(days=1))
    ot = _overtime(db, slot, workers)
    placed = _place(db, slot, workers, eff, ot, slot_ids)

    # 管理人员从班组里拿出来单独列（没有班组的人 rows 的键是 None）；其余只列本车间班组的（含借调来的人）
    mgr_rows = [(w, st, sup, tid) for tid, rs in placed.rows.items() for w, st, sup in rs if is_mgr(w)]
    rows = {tid: [r for r in rs if not is_mgr(r[0])] for tid, rs in placed.rows.items() if tid in dept_ids}
    unscheduled = sorted(w.name for w in workers if is_mgr(w) and eff[w.id][d].status is None)
    by_worker = _open_tasks(db, [w.id for rs in rows.values() for w, _s, _x in rs] + [w.id for w, *_ in mgr_rows])
    row = lambda w, st, sup, tid: _row(w, st, sup, tid, placed, ot, by_worker.get(w.id, []), member)

    order = [t.id for t in sorted(slot_teams, key=lambda t: not t.is_main)]
    order += [tid for tid in rows if tid not in order]
    top: list[DutyWorker] = []
    teams = []
    counts = {"on_duty": 0, "busy": 0, "idle": 0, "absent": 0, "off_hours": 0}
    for tid in order:
        out = []
        for w, st, support in rows.get(tid, []):
            r = row(w, st, support, tid)
            if r.status in ("busy", "idle"):
                counts["on_duty"] += 1
                counts[r.status] += 1
            elif r.status == "off_hours":
                counts["off_hours"] += 1
            else:
                counts["absent"] += 1
            (top if on_top(w) else out).append(r)
        out.sort(key=lambda r: (_status_order(r.status), r.worker.name))
        teams.append(DutyTeam(team_id=tid, workers=out))
    managers = sorted((row(w, st, sup, tid) for w, st, sup, tid in mgr_rows),
                      key=lambda r: (_status_order(r.status), r.worker.name))
    counts["managers_busy"] = sum(r.status == "busy" for r in managers)
    counts["managers_idle"] = sum(r.status == "idle" for r in managers)
    counts["managers"] = counts["managers_busy"] + counts["managers_idle"]
    top.sort(key=lambda r: (roles[r.role_id].sort_order if r.role_id in roles else 99,
                            order.index(r.team_id) if r.team_id in order else 99, r.worker.name))

    return DutyOut(
        which=which, shift_date=d, shift_kind=k, start=_local(start), end=_local(end),
        main_team_id=main.id if main else None, teams=teams, managers=managers, managers_unscheduled=unscheduled,
        top=top, counts=DutyCounts(**counts), can_add=_can_add(db, user, slot_ids),
    )
