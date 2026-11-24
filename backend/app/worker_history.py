"""员工的班组 / 个人排班变更记录（worker_schedules）。

出勤、工时、在岗人员按「当天有效的那一条」算：从 effective_from 起属于哪个班组、跟班组排班还是按个人循环。
workers.team_id 始终是「今天」所属的班组（方便权限、名单），由 sync_current 维护（定时任务每分钟检查一次，
所以提前登记的「下周一起调到 2 班」到那天会自动生效）。
"""

from bisect import bisect_right
from dataclasses import dataclass
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit
from .models import Worker, WorkerSchedule, utcnow
from .shifts import Cycle

EPOCH = date(2000, 1, 1)  # 最早的一条记录从这天起（等于「一直以来」）


@dataclass(frozen=True)
class Entry:
    effective_from: date
    team_id: int | None
    cycle: Cycle | None  # 个人循环；None = 跟班组排班


def to_cycle(pattern, start, holiday_off) -> Cycle | None:
    if not pattern or start is None:
        return None
    return Cycle(tuple(pattern), start, bool(holiday_off))


def _entry(r: WorkerSchedule) -> Entry:
    return Entry(r.effective_from, r.team_id, to_cycle(r.pattern, r.cycle_start, r.holiday_off))


class Timelines:
    """一批员工的变更记录，按日期查当天有效的那条。"""

    def __init__(self, db: Session, workers: list[Worker]):
        self._fallback = {w.id: Entry(EPOCH, w.team_id, None) for w in workers}
        self._rows: dict[int, list[Entry]] = {}
        ids = [w.id for w in workers]
        if ids:
            for r in db.scalars(select(WorkerSchedule).where(WorkerSchedule.worker_id.in_(ids))
                                .order_by(WorkerSchedule.worker_id, WorkerSchedule.effective_from)):
                self._rows.setdefault(r.worker_id, []).append(_entry(r))
        self._keys = {wid: [e.effective_from for e in rows] for wid, rows in self._rows.items()}

    def on(self, worker_id: int, d: date) -> Entry:
        rows = self._rows.get(worker_id)
        if not rows:
            return self._fallback.get(worker_id, Entry(EPOCH, None, None))
        i = bisect_right(self._keys[worker_id], d) - 1
        # 比第一条还早：按第一条算（第一条一般从 EPOCH 开始）
        return rows[max(i, 0)]

    def entries(self, worker_id: int) -> list[Entry]:
        return list(self._rows.get(worker_id) or [self._fallback.get(worker_id, Entry(EPOCH, None, None))])


def ensure_baseline(db: Session, worker: Worker, team_id: int | None) -> None:
    """还没有任何记录的员工（新建的、或迁移前漏掉的）：补一条「一直以来属于 team_id、跟班组排班」。"""
    if db.scalar(select(WorkerSchedule.id).where(WorkerSchedule.worker_id == worker.id).limit(1)) is None:
        db.add(WorkerSchedule(worker_id=worker.id, effective_from=EPOCH, team_id=team_id, created_at=utcnow()))
        db.flush()


def change_team(db: Session, worker: Worker, old_team: int | None, new_team: int | None, user_id: int | None,
                today: date) -> None:
    """名册里直接改班组：从今天起换班组，个人循环（如果有）保持不变。"""
    ensure_baseline(db, worker, old_team)
    cur = Timelines(db, [worker]).on(worker.id, today)
    record(db, worker, today, new_team, cur.cycle, user_id, today=today)


def record(db: Session, worker: Worker, effective_from: date, team_id: int | None, cycle: Cycle | None,
           user_id: int | None, note: str = "", today: date | None = None) -> None:
    """登记一次变更（同一天已有记录则覆盖），并更新 workers.team_id。"""
    from .schedule_service import local_now  # 避免循环引用

    ensure_baseline(db, worker, worker.team_id)
    row = db.scalar(select(WorkerSchedule).where(WorkerSchedule.worker_id == worker.id,
                                                 WorkerSchedule.effective_from == effective_from))
    before = Timelines(db, [worker]).on(worker.id, effective_from)
    vals = dict(team_id=team_id, pattern=list(cycle.pattern) if cycle else None,
                cycle_start=cycle.start if cycle else None, holiday_off=bool(cycle and cycle.holiday_off),
                note=note.strip()[:200], created_by=user_id, created_at=utcnow())
    if row is None:
        db.add(WorkerSchedule(worker_id=worker.id, effective_from=effective_from, **vals))
    else:
        for k, v in vals.items():
            setattr(row, k, v)
    audit.log(db, user_id=user_id, action="schedule", entity="worker", entity_id=worker.id, field="schedule",
              old=_describe(before), new=_describe(Entry(effective_from, team_id, cycle)),
              extra={"effective_from": str(effective_from), "note": note})
    db.flush()
    sync_worker(db, worker, today or local_now().date())


def remove(db: Session, worker: Worker, effective_from: date, user_id: int | None, today: date) -> bool:
    row = db.scalar(select(WorkerSchedule).where(WorkerSchedule.worker_id == worker.id,
                                                 WorkerSchedule.effective_from == effective_from))
    if row is None or effective_from == EPOCH:
        return False
    audit.log(db, user_id=user_id, action="schedule", entity="worker", entity_id=worker.id, field="schedule",
              old=_describe(_entry(row)), new=None, extra={"effective_from": str(effective_from), "removed": True})
    db.delete(row)
    db.flush()
    sync_worker(db, worker, today)
    return True


def _describe(e: Entry) -> dict:
    return {"from": str(e.effective_from), "team_id": e.team_id,
            "pattern": list(e.cycle.pattern) if e.cycle else None,
            "start": str(e.cycle.start) if e.cycle else None, "holiday_off": bool(e.cycle and e.cycle.holiday_off)}


def sync_worker(db: Session, worker: Worker, today: date) -> None:
    team = Timelines(db, [worker]).on(worker.id, today).team_id
    if worker.team_id != team:
        worker.team_id = team


def sync_current(db: Session, today: date) -> int:
    """把每个人的 workers.team_id 更新成今天有效的班组（提前登记的变更到日子自动生效）。返回改了几个。"""
    workers = list(db.scalars(select(Worker)))
    tl = Timelines(db, workers)
    n = 0
    for w in workers:
        team = tl.on(w.id, today).team_id
        if w.team_id != team:
            audit.log(db, user_id=None, action="schedule", entity="worker", entity_id=w.id, field="team_id",
                      old=w.team_id, new=team, extra={"auto": True, "day": str(today)})
            w.team_id = team
            n += 1
    if n:
        db.commit()
    return n


def members(db: Session, team_id: int, start: date, end: date, include_inactive: bool = False) -> list[Worker]:
    """这段时间里（任何一天）属于这个班组的员工（按变更记录算；换过班组的人在两边都会出现）。"""
    ids = set(db.scalars(select(WorkerSchedule.worker_id).where(WorkerSchedule.team_id == team_id)))
    q = select(Worker).where((Worker.id.in_(ids)) | (Worker.team_id == team_id))
    if not include_inactive:
        q = q.where(Worker.is_active.is_(True))
    workers = list(db.scalars(q))
    tl = Timelines(db, workers)
    out = []
    for w in workers:
        es = tl.entries(w.id)
        # 和 [start, end] 有交集的那几条里，有没有属于这个班组的
        for i, e in enumerate(es):
            nxt = es[i + 1].effective_from if i + 1 < len(es) else date.max
            if e.team_id == team_id and e.effective_from <= end and nxt > start:
                out.append(w)
                break
    return sorted(out, key=lambda w: w.name)
