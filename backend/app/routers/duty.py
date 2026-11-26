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


def _in_hours(sched, hours: str, d, now) -> bool:
    return any(a <= now < b for a, b in sched.entry_hours(hours, d))


def _next_start(sched, hours: str, d, now):
    """自定义上班时间里，now 之后最近一段的开始时间（本地 naive）；没有了返回 None。"""
    starts = [a for a, _b in sched.entry_hours(hours, d) if a > now]
    return min(starts) if starts else None


def _overlap(sched, row: dict, d, k, start, end, now):
    """有自定义上班时间、算在别的班（不是 k），但时间段有一部分落在班次 [start, end) 里的那一天的出勤
    （看当天和前一天）。now 给了（当前班次）就只看还没结束的部分。返回 (出勤, 从, 到) 或 None。"""
    for day in (d, d - timedelta(days=1)):
        a = row.get(day)
        if a is None or a.status != "present" or not a.hours or a.shift_kind == k:
            continue
        parts = [(max(x, start, now or start), min(y, end)) for x, y in sched.entry_hours(a.hours, day)]
        parts = [(x, y) for x, y in parts if x < y]
        if parts:
            return a, min(x for x, _ in parts), max(y for _, y in parts)
    return None


def _working_now(sched, row: dict, d, now):
    """有自定义上班时间、而且现在正在时间段里的那一天的出勤（看当天和前一天）；没有返回 None。"""
    for day in (d, d - timedelta(days=1)):
        a = row.get(day)
        if a is not None and a.status == "present" and a.hours and _in_hours(sched, a.hours, day, now):
            return a
    return None


@router.get("/duty", response_model=DutyOut)
def duty(which: str = Query(default="current", pattern="^(current|next)$"), db: Session = Depends(get_db),
         user: User = Depends(get_current_user), dept: int | None = Depends(get_dept)):
    """当前车间某个班次在岗的人：按出勤（含调班、顶班）算；忙碌 = 手上有未完成的任务（未开始或进行中）。
    别的车间借调来支援本车间班组的人也算在内（按他顶的班组）。"""
    sched = load_schedule(db)
    d, k = sched.shift_at(local_now())
    if which == "next":
        d, k = sched.next_shift(d, k)
    start, end = sched.shift_window(d, k)
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
    eff = att.effective(db, workers, d - timedelta(days=1), d)
    rows: dict[int, list[tuple[Worker, str, bool]]] = {}
    hours_of: dict[int, str | None] = {}
    back_of: dict[int, datetime] = {}
    overlap_of: dict[int, tuple[datetime, datetime]] = {}
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
                if (nx := _next_start(sched, a.hours, d, now)) is not None:
                    back_of[w.id] = nx
            hours_of[w.id] = a.hours
            rows.setdefault(team, []).append((w, st, team != w.team_id))
        elif which == "current" and (x := _working_now(sched, eff[w.id], d, now)) is not None:
            # 自定义上班时间跨过了班次分界（例如白班组 14:00-17:00，16:00 已经是中班时段）：现在在上班，也算在岗
            hours_of[w.id] = x.hours
            team = x.team_id or w.team_id
            rows.setdefault(team, []).append((w, "on", team != w.team_id))
        elif w.team_id in slot_ids and a.status in ("leave", "sick", "absent", "off") and a.source != "default":
            rows.setdefault(w.team_id, []).append((w, a.status, False))  # 本该上这个班，但请假 / 调走了
        elif (x := _overlap(sched, eff[w.id], d, k, start, end, now if which == "current" else None)) is not None:
            # 算在别的班（例如白班 07-12、14-17），但有一段时间落在这个班次里：也列出来、计入在岗，写明到几点
            a2, ov_from, ov_until = x
            team = a2.team_id or w.team_id
            hours_of[w.id] = a2.hours
            overlap_of[w.id] = (ov_from, ov_until)
            rows.setdefault(team, []).append((w, "on", team != w.team_id))

    # 管理人员从班组里拿出来单独列（没有班组的人 rows 的键是 None）
    mgr_rows = [(w, st, sup, tid) for tid, rs in rows.items() for w, st, sup in rs if is_mgr(w)]
    rows = {tid: [r for r in rs if not is_mgr(r[0])] for tid, rs in rows.items()
            if tid in dept_ids}  # 只列本车间班组的（含借调来的人）
    unscheduled = sorted(w.name for w in workers if is_mgr(w) and eff[w.id][d].status is None)
    ids = [w.id for rs in rows.values() for w, _s, _x in rs] + [w.id for w, *_ in mgr_rows]
    tasks = list(db.scalars(select(Task).options(selectinload(Task.workers))
                            .where(Task.status.in_(OPEN), Task.workers.any(Worker.id.in_(ids))))) if ids else []
    by_worker: dict[int, list[Task]] = {}
    for t in tasks:
        for w in t.workers:
            by_worker.setdefault(w.id, []).append(t)

    on_top = lambda w: role_of(w) is not None and role_of(w).show_on_top
    top: list[DutyWorker] = []
    teams, counts = [], {"managers": 0, "on_duty": 0, "busy": 0, "idle": 0, "absent": 0, "off_hours": 0}
    order = [t.id for t in sorted(slot_teams, key=lambda t: not t.is_main)]
    order += [tid for tid in rows if tid not in order]

    def entry(w, st, support, tid) -> DutyWorker:
        mine = sorted(by_worker.get(w.id, []), key=lambda t: (t.status != "in_progress", t.id))
        if st == "on":
            st = "busy" if mine else "idle"  # 分配了任务（未开始也算）就是忙碌
        return DutyWorker(
                hours=hours_of.get(w.id),
                back_at=back_of[w.id].replace(tzinfo=get_settings().tz) if w.id in back_of else None,
                overlap_from=overlap_of[w.id][0].replace(tzinfo=get_settings().tz) if w.id in overlap_of else None,
                overlap_until=overlap_of[w.id][1].replace(tzinfo=get_settings().tz) if w.id in overlap_of else None,
                worker=WorkerOut.model_validate(w), status=st, support=support, team_id=tid, role_id=w.role_id or member,
                overtime_until=ot[w.id][0].replace(tzinfo=get_settings().tz) if w.id in ot else None,
                overtime_prev=ot.get(w.id, (None, False))[1],
                tasks=[DutyTask(id=t.id, content=Trilingual(zh=t.content_zh, sr=t.content_sr, en=t.content_en),
                                source_lang=t.source_lang, status=t.status, is_lead=t.lead_worker_id == w.id,
                                team_id=t.team_id) for t in mine[:5]])

    for tid in order:
        out = []
        for w, st, support in rows.get(tid, []):
            r = entry(w, st, support, tid)
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
    managers = sorted((entry(w, st, sup, tid) for w, st, sup, tid in mgr_rows),
                      key=lambda r: (_status_order(r.status), r.worker.name))
    counts["managers_busy"] = sum(r.status == "busy" for r in managers)
    counts["managers_idle"] = sum(r.status == "idle" for r in managers)
    counts["managers"] = counts["managers_busy"] + counts["managers_idle"]

    tz = get_settings().tz
    return DutyOut(
        which=which, shift_date=d, shift_kind=k, start=start.replace(tzinfo=tz), end=end.replace(tzinfo=tz),
        main_team_id=main.id if main else None, teams=teams, managers=managers, managers_unscheduled=unscheduled,
        top=sorted(top, key=lambda r: (roles[r.role_id].sort_order if r.role_id in roles else 99, order.index(r.team_id)
                                       if r.team_id in order else 99, r.worker.name)), counts=DutyCounts(**counts),
        can_add=(lambda w: w.has("task.create") and (w.is_admin or w.scope("task.create") in ("dept", "all")
                                                     and any(w.team_ok("task.create", t) for t in slot_ids)
                                                     or user.team_id in slot_ids))(permissions.who(db, user)),
    )
