"""「为什么？」：某人某天 / 某班组某天的排班是怎么得出来的。

不另写一套规则：直接调用业务代码用的同一批函数（attendance_service.resolve、Schedule.shift_of），
让它们把每一步依据记进 trace，再补上「谁、什么时候设的」。所以解释和实际结果不会对不上。

每一步是 {"code": ..., ...}，前端按 code 翻成三语句子（frontend/src/components/WhyPanel.vue）。
code 一览（按出现的先后）：
  membership     名册：这天属于哪个班组（since = 从哪天起；EPOCH = 一直以来）、是否个人循环
  personal_cycle 按个人循环（不跟班组）
  team_cycle     按班组排班（manual = 不固定班组，没有循环）
  inactive       临时班组不在有效期内 → 休息
  cycle          循环第 pos / length 天写的是 entry
  holiday        节假日休息（原本 was）
  workday        调休上班日，按主要班次 entry 上
  team_override  班组调班：改成 entry（原本 planned）
  hours_kind     自定义时间段 hours 算作 kind 班
  member_shift   （班组）班组本身休息，但有成员被单独安排上 kind 班 → 班组也算在班（workers = 哪些人）
  attendance     出勤例外记录（导入 / 手工改）：status、shift_kind、顶哪个班组 team_id、备注
  cover          去顶 team_id 的班、没写班次 → 按那个班组当天的 kind
  hours_dropped  例外改了班次，原来的自定义时间段 hours 不再适用
  group          这个班次合并显示在 main 那一组（team_ids）；alone = 他的班组当天不上这个班，是单独安排来的
  overtime       加班到 until（hours 小时）
"""

import dataclasses
from datetime import date, datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import attendance_service as att
from .models import Attendance, Holiday, Team, TeamShiftOverride, User, Worker, WorkerSchedule
from .overtime_service import expand as expand_overtime
from .schedule_service import load_schedule
from .shifts import OFF, Schedule, note
from .worker_history import EPOCH, Timelines


def _utc(dt: datetime | None) -> datetime | None:
    if dt is not None and dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _enrich(db: Session, steps: list[dict], d: date, worker: Worker | None = None) -> list[dict]:
    """补上每一步是谁、什么时候设的，以及节假日名称。"""
    for s in steps:
        c = s["code"]
        if c == "team_override":
            o = db.scalar(select(TeamShiftOverride).where(TeamShiftOverride.team_id == s["team_id"],
                                                          TeamShiftOverride.day == d))
            if o is not None:
                s.update(by=o.created_by, at=o.created_at, note=o.note)
        elif c == "membership" and worker is not None:
            s["always"] = s["since"] == EPOCH
            r = db.scalar(select(WorkerSchedule).where(WorkerSchedule.worker_id == worker.id,
                                                       WorkerSchedule.effective_from == s["since"]))
            if r is not None and not s["always"]:
                s.update(by=r.created_by, at=r.created_at, note=r.note)
        elif c == "holiday":
            h = db.get(Holiday, d)
            s["name"] = h.name if h else ""
    ids = {s["by"] for s in steps if s.get("by")}
    names = {u.id: u.full_name or u.username for u in db.scalars(select(User).where(User.id.in_(ids)))} if ids else {}
    for s in steps:
        if "by" in s:
            s["by_name"] = names.get(s["by"], "")
        if "at" in s:
            s["at"] = _utc(s["at"])
    return steps


def _group(sched: Schedule, trace: list, team_id: int | None, d: date, kind: str) -> None:
    team = sched.team(team_id)
    if team is None or kind in (None, OFF):
        return
    if sched.is_on(team, d, kind):
        grp = sched.group_of(team, d, kind)
        note(trace, "group", kind=kind, main=grp[0].id, team_ids=[t.id for t in grp], alone=False)
    else:
        main = sched.main_team_on(d, kind, team.dept)
        note(trace, "group", kind=kind, main=main.id if main else None,
             team_ids=[main.id] if main else [], alone=True)


def worker_day(db: Session, worker: Worker, d: date) -> dict:
    sched = load_schedule(db)
    entry = Timelines(db, [worker]).on(worker.id, d)
    a = db.scalar(select(Attendance).where(Attendance.worker_id == worker.id, Attendance.day == d))
    trace: list = []
    res = att.resolve(sched, entry, a, d, trace)
    if res.status == "present":
        _group(sched, trace, res.team_id, d, res.shift_kind)
    for x in expand_overtime(db, d, d, [worker]):
        note(trace, "overtime", kind=x.shift_kind, until=x.until_local, hours=x.hours, whole_team=x.whole_team)
    return {"day": d, "result": dataclasses.asdict(res), "steps": _enrich(db, trace, d, worker)}


def _member_workers(db: Session, sched: Schedule, team_id: int, d: date, kind: str) -> list[dict]:
    """班组因为成员被单独安排上班才算在班时，是哪些人（和 schedule_service.member_days 同一个算法）。"""
    own = dataclasses.replace(sched, member_fn=None, _member_cache={})
    ids = set(db.scalars(select(Worker.id).where(Worker.team_id == team_id)))
    ids |= set(db.scalars(select(WorkerSchedule.worker_id).where(WorkerSchedule.team_id == team_id)))
    ids |= set(db.scalars(select(Attendance.worker_id).where(Attendance.team_id == team_id, Attendance.day == d)))
    workers = list(db.scalars(select(Worker).where(Worker.id.in_(ids), Worker.is_active.is_(True)))) if ids else []
    eff = att.effective(db, workers, d, d, own)
    return [{"id": w.id, "name": w.name} for w in sorted(workers, key=lambda w: w.name)
            if (x := eff[w.id][d]).status == "present" and x.shift_kind == kind and x.team_id == team_id]


def team_day(db: Session, team: Team, d: date) -> dict:
    sched = load_schedule(db)
    info = sched.team(team.id)
    trace: list = []
    kind = sched.shift_of(info, d, trace)
    entry = sched.team_entry(info, d)
    for s in trace:
        if s["code"] == "member_shift":
            s["workers"] = _member_workers(db, sched, team.id, d, s["kind"])
    if kind != OFF:
        _group(sched, trace, team.id, d, kind)
    return {"day": d, "result": {"kind": kind, "entry": entry, "team_id": team.id},
            "steps": _enrich(db, trace, d)}
