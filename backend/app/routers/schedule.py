"""班组、排班、节假日。"""

from datetime import date, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, departments, permissions, translation_service
from ..departments import get_dept
from ..db import get_db
from ..db import Base
from ..models import Department, Holiday, ShiftConfig, Team, TeamShiftOverride, User, Worker, utcnow
from ..schedule_service import load_schedule, local_now, slot
from ..schemas import (
    CalendarDay,
    HolidayIO,
    ShiftConfigIn,
    ShiftConfigOut,
    ShiftNow,
    TeamOut,
)
from pydantic import BaseModel, Field

from ..security import get_current_user, require_admin
from ..shifts import KINDS, MAX_CYCLE, OFF, check_hours, coverage_problems, parse_hours

router = APIRouter(prefix="/api", tags=["schedule"])


@router.get("/teams", response_model=list[TeamOut])
def list_teams(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    """所有车间的班组（每个带 department_id；前端按当前车间筛，跨车间移交时列出别的车间）。"""
    return db.scalars(select(Team).order_by(Team.sort_order)).all()


@router.get("/shifts/now", response_model=ShiftNow)
def shifts_now(db: Session = Depends(get_db), _: User = Depends(get_current_user), dept: int | None = Depends(get_dept)):
    sched = load_schedule(db)
    now = local_now()
    d, k = sched.shift_at(now)
    nd, nk = sched.next_shift(d, k)
    return ShiftNow(now=now, current=slot(sched, d, k, dept), next=slot(sched, nd, nk, dept))


@router.get("/shifts/calendar", response_model=list[CalendarDay])
def shifts_calendar(start: date, end: date, db: Session = Depends(get_db),
                    _: User = Depends(get_current_user), dept: int | None = Depends(get_dept)):
    """当前车间的排班日历。"""
    if end < start or (end - start).days > 92:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "range must be 0..92 days")
    sched = load_schedule(db)
    teams = [t for t in sched.teams if t.dept == dept]
    out = []
    d = start
    while d <= end:
        out.append(CalendarDay(day=d, workday=sched.is_workday(d),
                               shifts={t.id: sched.shift_of(t, d) for t in teams},
                               hours={t.id: e for t in teams if parse_hours(e := sched.team_entry(t, d))},
                               changed={t.id: sched.planned_shift_of(t, d) for t in teams
                                        if (t.id, d) in sched.overrides},
                               by_members=[t.id for t in teams if sched.entry_kind(sched.team_entry(t, d)) == "off"
                                           and sched.shift_of(t, d) != "off"]))
        d += timedelta(days=1)
    return out


@router.get("/shifts/config", response_model=ShiftConfigOut)
def get_config(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.get(ShiftConfig, 1)


@router.put("/shifts/config", response_model=ShiftConfigOut)
def put_config(body: ShiftConfigIn, db: Session = Depends(get_db),
               admin: User = Depends(require_admin)):
    """班次时间。各班组的循环在「班组管理」里各自设置。"""
    if not (body.day_start < body.middle_start < body.night_start):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "shift start times must be increasing")
    cfg = db.get(ShiftConfig, 1)
    audit.log_changes(db, cfg, body.model_dump(), user_id=admin.id, entity="shift_config", entity_id=1)
    db.commit()
    return cfg


@router.get("/holidays", response_model=list[HolidayIO])
def list_holidays(year: int | None = Query(default=None), db: Session = Depends(get_db),
                  _: User = Depends(get_current_user)):
    q = select(Holiday).order_by(Holiday.day)
    if year:
        q = q.where(Holiday.day >= date(year, 1, 1), Holiday.day <= date(year, 12, 31))
    return db.scalars(q).all()


@router.put("/holidays/{day}", response_model=HolidayIO)
def put_holiday(day: date, body: HolidayIO, db: Session = Depends(get_db),
                admin: User = Depends(require_admin)):
    h = db.get(Holiday, day)
    if h is None:
        h = Holiday(day=day, name=body.name, kind=body.kind)
        db.add(h)
        audit.log(db, user_id=admin.id, action="create", entity="holiday", entity_id=day,
                  new={"name": body.name, "kind": body.kind})
    else:
        audit.log_changes(db, h, {"name": body.name, "kind": body.kind}, user_id=admin.id,
                          entity="holiday", entity_id=day)
    db.commit()
    return h


@router.delete("/holidays/{day}", status_code=204)
def delete_holiday(day: date, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    h = db.get(Holiday, day)
    if h is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    audit.log(db, user_id=admin.id, action="delete", entity="holiday", entity_id=day, old=h.name)
    db.delete(h)
    db.commit()


# ---------------- 班组整体调班 ----------------
class TeamShiftIn(BaseModel):
    team_id: int
    start: date
    end: date
    shift_kind: str = Field(default="day", pattern="^(day|middle|night|off)$")
    hours: str | None = Field(default=None, max_length=60)  # 自定义时间段（填了就按它，shift_kind 忽略）
    note: str = Field(default="", max_length=200)


class TeamShiftOut(BaseModel):
    team_id: int
    day: date
    shift_kind: str  # 算作哪个班
    hours: str | None  # 自定义时间段
    planned: str  # 原本按排班该上的（班次或时间段）
    note: str


def _ts_out(sched, o: TeamShiftOverride) -> TeamShiftOut:
    team = next(t for t in sched.teams if t.id == o.team_id)
    return TeamShiftOut(team_id=o.team_id, day=o.day, shift_kind=o.shift_kind, hours=o.hours,
                        planned=sched.planned_entry(team, o.day), note=o.note)


def _range(start: date, end: date) -> list[date]:
    if end < start or (end - start).days > 30:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "range must be 1..31 days")
    return [start + timedelta(days=i) for i in range((end - start).days + 1)]


@router.get("/team-shifts", response_model=list[TeamShiftOut])
def list_team_shifts(start: date, end: date, db: Session = Depends(get_db), _: User = Depends(get_current_user),
                     dept: int | None = Depends(get_dept)):
    """当前车间各班组的整体调班。"""
    sched = load_schedule(db)
    ids = departments.team_ids(db, dept)
    rows = db.scalars(select(TeamShiftOverride).where(TeamShiftOverride.day >= start, TeamShiftOverride.day <= end,
                                                      TeamShiftOverride.team_id.in_(ids))
                      .order_by(TeamShiftOverride.day, TeamShiftOverride.team_id)).all()
    return [_ts_out(sched, o) for o in rows]


@router.put("/team-shifts", response_model=list[TeamShiftOut])
def set_team_shift(body: TeamShiftIn, db: Session = Depends(get_db), admin: User = Depends(get_current_user)):
    """某个班组在某几天整体改上某个班（或休息）。和原排班相同的日子不记录（等于恢复）。
    管理员任何班组；班长只能调本班组（临时调班）。"""
    team = db.get(Team, body.team_id)
    if team is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "team not found")
    _require_team(db, admin, team.id)
    entry = body.shift_kind
    if body.hours and body.hours.strip():
        try:
            entry = check_hours(body.hours.replace(" ", "").replace("，", ","))
        except ValueError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"bad hours: {e}") from e
        if parse_hours(entry) is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "bad hours: format HH:MM-HH:MM")
    _apply_team_shift(db, team.id, _range(body.start, body.end), lambda _d: entry, body.note, admin.id)
    db.commit()
    return list_team_shifts(body.start, body.end, db, admin, team.department_id)


def _require_team(db: Session, user: User, *team_ids: int) -> None:
    who = permissions.who(db, user)
    if not any(who.team_ok("schedule.team_shift", t) for t in team_ids):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your team")


def _apply_team_shift(db: Session, team_id: int, days: list[date], kind_of, note: str, user_id: int) -> None:
    """把班组在这些天改成 kind_of(日期)（班次或自定义时间段）；和原排班一样的日子删掉覆盖记录。"""
    sched = load_schedule(db)
    info = next(t for t in sched.teams if t.id == team_id)
    for d in days:
        entry = kind_of(d)
        kind = sched.entry_kind(entry)
        hours = entry if entry != kind else None
        row = db.scalar(select(TeamShiftOverride).where(TeamShiftOverride.team_id == team_id,
                                                        TeamShiftOverride.day == d))
        old = sched.team_entry(info, d)
        if entry == sched.planned_entry(info, d):
            if row:
                db.delete(row)
        elif row:
            row.shift_kind, row.hours, row.note = kind, hours, note.strip()
        else:
            db.add(TeamShiftOverride(team_id=team_id, day=d, shift_kind=kind, hours=hours, note=note.strip(),
                                     created_by=user_id, created_at=utcnow()))
        kind = entry  # 留痕记写法（含时间段）
        if old != kind:
            audit.log(db, user_id=user_id, action="update", entity="team", entity_id=team_id,
                      field="team_shift", old=f"{d} {old}", new=f"{d} {kind}",
                      extra={"day": str(d), "note": note})
    db.flush()


class TeamSwapIn(BaseModel):
    team_a: int
    team_b: int
    start: date
    end: date
    note: str = Field(default="", max_length=200)


@router.post("/team-shifts/swap", response_model=list[TeamShiftOut])
def swap_team_shifts(body: TeamSwapIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """两个班组在这几天互换班次（临时调班）。班长只要其中一个是本班组即可。"""
    if body.team_a == body.team_b:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "need two different teams")
    if db.get(Team, body.team_a) is None or db.get(Team, body.team_b) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "team not found")
    _require_team(db, user, body.team_a, body.team_b)
    days = _range(body.start, body.end)
    sched = load_schedule(db)
    a = next(t for t in sched.teams if t.id == body.team_a)
    b = next(t for t in sched.teams if t.id == body.team_b)
    shift_a = {d: sched.team_entry(a, d) for d in days}  # 先记下互换前的（含自定义时间段）
    shift_b = {d: sched.team_entry(b, d) for d in days}
    _apply_team_shift(db, a.id, days, lambda d: shift_b[d], body.note, user.id)
    _apply_team_shift(db, b.id, days, lambda d: shift_a[d], body.note, user.id)
    db.commit()
    return list_team_shifts(body.start, body.end, db, user, a.dept)


class UnaffectedOut(BaseModel):
    worker_id: int
    name: str
    reason: str  # personal（按个人循环）/ attendance（这天有出勤记录：请假、顶班、改班次……）
    days: list[date]


@router.get("/team-shifts/unaffected", response_model=list[UnaffectedOut])
def team_shift_unaffected(team_id: int, start: date, end: date, db: Session = Depends(get_db),
                          _: User = Depends(get_current_user)):
    """这个班组这几天里，班组调班对他不起作用的人：按个人循环上班的，或那天有出勤记录的（以出勤为准）。
    调班保存后前端提示用。判定和 attendance_service.resolve 一致（个人循环不看班组排班，出勤记录优先）。"""
    from .. import worker_history
    from ..models import Attendance

    days = _range(start, end)
    workers = worker_history.members(db, team_id, start, end)
    if not workers:
        return []
    tl = worker_history.Timelines(db, workers)
    recs = {(a.worker_id, a.day) for a in db.scalars(select(Attendance).where(
        Attendance.worker_id.in_([w.id for w in workers]), Attendance.day.in_(days)))}
    out: dict = {}
    for w in workers:
        for d in days:
            e = tl.on(w.id, d)
            if e.team_id != team_id:
                continue
            reason = "attendance" if (w.id, d) in recs else "personal" if e.cycle is not None else None
            if reason:
                out.setdefault((w.id, reason), UnaffectedOut(worker_id=w.id, name=w.name, reason=reason, days=[])).days.append(d)
    return sorted(out.values(), key=lambda x: (x.reason, x.name))


@router.delete("/team-shifts", status_code=204)
def clear_team_shift(team_id: int, start: date, end: date, db: Session = Depends(get_db),
                     admin: User = Depends(get_current_user)):
    """恢复按排班。"""
    _require_team(db, admin, team_id)
    sched = load_schedule(db)
    info = next((t for t in sched.teams if t.id == team_id), None)
    if info is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "team not found")
    days = _range(start, end)
    for row in db.scalars(select(TeamShiftOverride).where(TeamShiftOverride.team_id == team_id,
                                                          TeamShiftOverride.day.in_(days))).all():
        audit.log(db, user_id=admin.id, action="update", entity="team", entity_id=team_id, field="team_shift",
                  old=f"{row.day} {row.hours or row.shift_kind}", new=f"{row.day} {sched.planned_entry(info, row.day)}",
                  extra={"day": str(row.day), "restore": True})
        db.delete(row)
    db.commit()


# ---------------- 班组管理（管理员、有「班组管理」权限的车间管理员）：新增长期 / 临时班组 ----------------
class TeamIn(BaseModel):
    department_id: int | None = None  # 属于哪个车间（空 = 当前车间）
    name_zh: str = Field(default="", max_length=50)
    name_sr: str = Field(default="", max_length=50)
    name_en: str = Field(default="", max_length=50)
    kind: str = Field(pattern="^(cycle|manual)$")  # 按循环排班 / 不固定（只按调班）
    pattern: list[str] | None = None  # 循环里每天的班：day / middle / night / off
    cycle_start: date | None = None  # 循环第 1 天
    holiday_off: bool = False
    is_main: bool = False
    active_from: date | None = None
    active_to: date | None = None


def check_cycle(pattern: list[str] | None, start: date | None) -> list[str]:
    """校验循环设置（班组和个人排班共用）。"""
    if not pattern or start is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "cycle pattern and start date required")
    if not 1 <= len(pattern) <= MAX_CYCLE:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"pattern must be 1..{MAX_CYCLE} days of day/middle/night/off")
    out = []
    for k in pattern:  # 班次，或自定义上班时间段（例如 07:00-12:00,14:00-17:00）
        try:
            out.append(k if k in KINDS else check_hours(str(k)))
        except ValueError as e:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"bad hours {k!r}: {e}")
    if all(k == OFF for k in out):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "pattern has no working day")
    return out


def _team_fields(db: Session, body: TeamIn) -> dict:
    names = {k: getattr(body, k).strip() for k in ("name_zh", "name_sr", "name_en")}
    first = next((v for v in names.values() if v), "")
    if not first:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "team name required")
    # 没填的语言自动翻译（没配翻译就先用填了的那个）
    filled = translation_service.fill_names({k[5:]: v for k, v in names.items()})
    names = {f"name_{l}": translation_service.fit(filled[l], 50) for l in ("zh", "sr", "en")}
    if body.active_from and body.active_to and body.active_to < body.active_from:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "active_to before active_from")
    if body.kind == "cycle":
        cyc = dict(pattern=check_cycle(body.pattern, body.cycle_start), cycle_start=body.cycle_start,
                   holiday_off=body.holiday_off)
    else:
        cyc = dict(pattern=None, cycle_start=None, holiday_off=False)
    return {**names, "kind": body.kind, **cyc, "is_main": body.is_main,
            "active_from": body.active_from, "active_to": body.active_to}


def _require_team_manage(db: Session, user: User, dept_id: int | None) -> None:
    if dept_id is None or db.get(Department, dept_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "department not found")
    if not permissions.who(db, user).dept_ok("team.manage", dept_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your department")


@router.post("/teams", response_model=TeamOut, status_code=201)
def create_team(body: TeamIn, db: Session = Depends(get_db), admin: User = Depends(get_current_user),
                dept: int | None = Depends(get_dept)):
    dept_id = body.department_id or dept
    _require_team_manage(db, admin, dept_id)
    d = _team_fields(db, body) | {"department_id": dept_id}
    n = (db.scalar(select(func.max(Team.id))) or 0) + 1
    code = f"X{n}"
    while db.scalar(select(Team.id).where(Team.code == code)):
        n += 1
        code = f"X{n}"
    t = Team(code=code, sort_order=(db.scalar(select(func.max(Team.sort_order))) or 0) + 1, **d)
    db.add(t)
    db.flush()
    audit.log(db, user_id=admin.id, action="create", entity="team", entity_id=t.id,
              new={k: (str(v) if isinstance(v, date) else v) for k, v in d.items()})
    db.commit()
    return t


@router.put("/teams/{team_id}", response_model=TeamOut)
def update_team(team_id: int, body: TeamIn, db: Session = Depends(get_db), admin: User = Depends(get_current_user)):
    t = db.get(Team, team_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    _require_team_manage(db, admin, t.department_id)
    dept_id = body.department_id or t.department_id
    if dept_id != t.department_id:  # 换车间：两边都要能管
        _require_team_manage(db, admin, dept_id)
    audit.log_changes(db, t, _team_fields(db, body) | {"department_id": dept_id}, user_id=admin.id,
                      entity="team", entity_id=t.id)
    db.flush()
    for w in db.scalars(select(Worker).where(Worker.team_id == t.id, Worker.department_id != dept_id)):
        w.department_id = dept_id  # 员工跟着班组换车间
    db.commit()
    return t


def _team_refs(db: Session, team_id: int) -> int:
    """其他表里还有多少条记录引用这个班组（不含它自己的调班记录）。"""
    n = 0
    for table in Base.metadata.sorted_tables:
        if table.name == "team_shift_overrides":
            continue
        for col in table.columns:
            if any(fk.column.table.name == "teams" for fk in col.foreign_keys):
                n += db.scalar(select(func.count()).select_from(table).where(col == team_id)) or 0
    return n


@router.delete("/teams/{team_id}", status_code=204)
def delete_team(team_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_user)):
    """只能删除没用过的班组（没有员工、账号、任务、出勤、加班、巡查……）；用过的请设置结束日期。"""
    t = db.get(Team, team_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    _require_team_manage(db, admin, t.department_id)
    if _team_refs(db, team_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "team in use; set an end date instead")
    for o in db.scalars(select(TeamShiftOverride).where(TeamShiftOverride.team_id == team_id)).all():
        db.delete(o)
    db.flush()  # 先删调班记录，再删班组（两者之间没有 relationship，不 flush 的话删除顺序不确定）
    audit.log(db, user_id=admin.id, action="delete", entity="team", entity_id=team_id,
              old={"name_zh": t.name_zh, "kind": t.kind, "pattern": t.pattern})
    db.delete(t)
    db.commit()


# ---------------- 排班检查：有没有哪个班次没人上 ----------------
class CoverageProblem(BaseModel):
    day: date
    shift_kind: str
    problem: str  # none / nomain / multiple
    team_ids: list[int]


@router.get("/shifts/coverage", response_model=list[CoverageProblem])
def shifts_coverage(start: date, end: date, db: Session = Depends(get_db), _: User = Depends(get_current_user),
                    dept: int | None = Depends(get_dept)):
    """当前车间的排班检查。"""
    if end < start or (end - start).days > 92:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "range must be 0..92 days")
    return [CoverageProblem(day=d, shift_kind=k, problem=p, team_ids=ids)
            for d, k, p, ids in coverage_problems(load_schedule(db), start, end, dept)]
