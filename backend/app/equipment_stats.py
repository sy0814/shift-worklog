"""设备统计：按设备汇总一段时间里的任务。

计数单位是「移交链」，不是任务条数：一件事移交了两次会有 3 条任务，只算 1 次。
链从第一条任务（source_task_id 为空）开始，它的班次日期落在时间段里才算；状态、类型、完成时间看链上最新的一条。
移交时新任务会复制原任务的开始时间，所以「处理用时」直接用最新一条的 完成 − 开始，不能把链上每条加起来。

指标：
  fault / maintenance / inspection / other  各类型的次数（任务类型 tasks.kind）
  open      还没完成的（未开始 / 进行中）；overdue 其中超过「未闭环警示」小时数的
  avg_hours 平均从录入到完成（小时，不算巡查）
  work_hours 处理用时合计（开始 → 完成）
  handovers 移交次数合计；logs 班次日志条数
  repeat    30 天内故障 ≥ REPEAT_N 次；repeat_max 任意 30 天里最多几次故障
"""

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from . import app_settings
from .models import Equipment, Task, TaskLog

REPEAT_DAYS = 30
REPEAT_N = 3
OPEN = ("not_started", "in_progress")


def _aware(d: datetime | None) -> datetime | None:
    if d is not None and d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d


@dataclass
class Chain:
    root: Task
    tasks: list[Task]

    @property
    def last(self) -> Task:
        return self.tasks[-1]

    @property
    def kind(self) -> str:
        return self.last.kind or "other"

    @property
    def started(self) -> datetime:
        return _aware(self.root.chain_started_at or self.root.recorded_at)

    @property
    def done_at(self) -> datetime | None:
        return _aware(self.last.end_at) if self.last.status == "done" else None


def chains(db: Session, equipment_ids: list[int], start: date, end: date) -> dict[int, list[Chain]]:
    """{设备 id: [移交链]}，链的第一条任务班次日期在 [start, end] 里。"""
    if not equipment_ids:
        return {}
    rows = list(db.scalars(select(Task).where(Task.equipment_id.in_(equipment_ids), Task.shift_date >= start)
                           .order_by(Task.id)))
    child = {t.source_task_id: t for t in rows if t.source_task_id}
    out: dict[int, list[Chain]] = defaultdict(list)
    for t in rows:
        if t.source_task_id is not None or t.shift_date > end:
            continue
        seq = [t]
        while seq[-1].id in child and len(seq) < 100:
            seq.append(child[seq[-1].id])
        out[t.equipment_id].append(Chain(t, seq))
    return out


@dataclass
class Row:
    equipment: Equipment
    counts: dict = field(default_factory=lambda: dict.fromkeys(("fault", "maintenance", "inspection", "other"), 0))
    total: int = 0
    open: int = 0
    overdue: int = 0
    avg_hours: float | None = None
    work_hours: float = 0.0
    handovers: int = 0
    logs: int = 0
    last_at: datetime | None = None
    repeat_max: int = 0

    @property
    def repeat(self) -> bool:
        return self.repeat_max >= REPEAT_N


def build(db: Session, equipment: list[Equipment], start: date, end: date, now: datetime) -> list[Row]:
    ids = [e.id for e in equipment]
    by_eq = chains(db, ids, start, end)
    all_ids = [t.id for cs in by_eq.values() for c in cs for t in c.tasks]
    log_counts: dict[int, int] = {}
    if all_ids:
        log_counts = dict(db.execute(select(TaskLog.task_id, func.count()).where(
            TaskLog.task_id.in_(all_ids), TaskLog.deleted_at.is_(None)).group_by(TaskLog.task_id)).all())
    overdue_h = float(app_settings.get(db, "overdue_hours") or 24)
    rows = []
    for e in equipment:
        cs = by_eq.get(e.id, [])
        if not cs:
            continue
        r = Row(e)
        durations = []
        faults = []
        for c in cs:
            r.counts[c.kind] = r.counts.get(c.kind, 0) + 1
            r.total += 1
            r.handovers += len(c.tasks) - 1
            r.logs += sum(log_counts.get(t.id, 0) for t in c.tasks)
            r.last_at = max(r.last_at or c.started, c.started)
            if c.last.status in OPEN:
                r.open += 1
                if (now - c.started).total_seconds() / 3600 > overdue_h:
                    r.overdue += 1
            if c.done_at:
                if c.kind != "inspection":
                    durations.append((c.done_at - c.started).total_seconds() / 3600)
                if c.last.start_at:
                    r.work_hours += max(0.0, (c.done_at - _aware(c.last.start_at)).total_seconds() / 3600)
            if c.kind == "fault":
                faults.append(c.started)
        if durations:
            r.avg_hours = round(sum(durations) / len(durations), 1)
        r.work_hours = round(r.work_hours, 1)
        faults.sort()
        j = 0
        for i, f in enumerate(faults):  # 滑动窗口：任意 30 天里最多几次故障
            while f - faults[j] > timedelta(days=REPEAT_DAYS):
                j += 1
            r.repeat_max = max(r.repeat_max, i - j + 1)
        rows.append(r)
    rows.sort(key=lambda r: (-r.counts["fault"], -r.total, r.equipment.code))
    return rows
