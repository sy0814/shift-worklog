"""设备统计（「设备台账 → 统计」）：每台设备在一段时间里出了几次故障、检修几次、平均多久修好、哪些反复出问题。
计算在 app/equipment_stats.py。能看本车间所有任务的人（管理员、车间管理员）和能管设备的人（班长、副班长）能看。"""

import io
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.responses import StreamingResponse
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit, equipment_stats as es, permissions
from ..config import get_settings
from ..db import get_db
from ..departments import get_dept
from ..models import Equipment, Task, TaskLog, User, Worker, utcnow
from ..schemas import Lang, Trilingual, UTCDateTime
from ..security import get_current_user
from .equipment import _in_dept

router = APIRouter(prefix="/api/equipment-stats", tags=["equipment"])
MAX_DAYS = 366


class EqBrief(BaseModel):
    id: int
    code: str
    name: Trilingual
    area: Trilingual
    source_lang: str
    is_active: bool


class StatRow(BaseModel):
    equipment: EqBrief
    fault: int
    maintenance: int
    inspection: int
    other: int
    total: int
    open: int
    overdue: int
    avg_hours: float | None
    work_hours: float
    handovers: int
    logs: int
    last_at: UTCDateTime | None
    repeat: bool
    repeat_max: int


class StatsOut(BaseModel):
    start: date
    end: date
    repeat_days: int = es.REPEAT_DAYS
    repeat_n: int = es.REPEAT_N
    items: list[StatRow]
    idle: int  # 这段时间没有任务的设备台数


class LogBrief(BaseModel):
    content: Trilingual
    source_lang: str
    author: str
    recorded_at: UTCDateTime
    shift_date: date
    shift_kind: str


class ChainOut(BaseModel):
    task_id: int  # 第一条
    last_task_id: int
    kind: str
    content: Trilingual
    source_lang: str
    started_at: UTCDateTime
    status: str
    done_at: UTCDateTime | None
    hours: float | None  # 从录入到完成
    team_ids: list[int]  # 经过的班组（按先后）
    logs: list[LogBrief]


def _check(db: Session, user: User) -> None:
    w = permissions.who(db, user)
    ok = user.role == "admin" or w.scope("task.view") in ("dept", "all") or w.has("equipment.manage")
    permissions.require(ok, "no permission to view equipment statistics")


def _range(start: date | None, end: date | None) -> tuple[date, date]:
    from ..schedule_service import local_now

    end = end or local_now().date()
    start = start or end - timedelta(days=89)
    if end < start or (end - start).days >= MAX_DAYS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"range must be 1..{MAX_DAYS} days")
    return start, end


def _brief(e: Equipment) -> EqBrief:
    return EqBrief(id=e.id, code=e.code, name=Trilingual(zh=e.name_zh, sr=e.name_sr, en=e.name_en),
                   area=Trilingual(zh=e.area_zh, sr=e.area_sr, en=e.area_en), source_lang=e.source_lang,
                   is_active=e.is_active)


def _stats(db: Session, dept: int | None, start: date, end: date) -> tuple[list[es.Row], int]:
    equipment = list(db.scalars(_in_dept(select(Equipment), dept).order_by(Equipment.code)))
    rows = es.build(db, equipment, start, end, utcnow())
    idle = sum(1 for e in equipment if e.is_active) - sum(1 for r in rows if r.equipment.is_active)
    return rows, idle


@router.get("", response_model=StatsOut)
def get_stats(start: date | None = None, end: date | None = None, db: Session = Depends(get_db),
              user: User = Depends(get_current_user), dept: int | None = Depends(get_dept)):
    _check(db, user)
    start, end = _range(start, end)
    rows, idle = _stats(db, dept, start, end)
    return StatsOut(start=start, end=end, idle=idle, items=[StatRow(
        equipment=_brief(r.equipment), **r.counts, total=r.total, open=r.open, overdue=r.overdue,
        avg_hours=r.avg_hours, work_hours=r.work_hours, handovers=r.handovers, logs=r.logs, last_at=r.last_at,
        repeat=r.repeat, repeat_max=r.repeat_max) for r in rows])


@router.get("/{eid}/timeline", response_model=list[ChainOut])
def timeline(eid: int, start: date | None = None, end: date | None = None, db: Session = Depends(get_db),
             user: User = Depends(get_current_user)):
    """这台设备在这段时间里的每一件事（移交链），新的在前，带上链上所有班次日志。"""
    _check(db, user)
    if db.get(Equipment, eid) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    start, end = _range(start, end)
    cs = es.chains(db, [eid], start, end).get(eid, [])
    ids = [t.id for c in cs for t in c.tasks]
    logs = list(db.scalars(select(TaskLog).where(TaskLog.task_id.in_(ids), TaskLog.deleted_at.is_(None))
                           .order_by(TaskLog.recorded_at))) if ids else []
    wn = dict(db.execute(select(Worker.id, Worker.name)).all()) if logs else {}
    un = {u.id: u.full_name or u.username for u in db.scalars(select(User))} if logs else {}
    by_task: dict[int, list[TaskLog]] = {}
    for x in logs:
        by_task.setdefault(x.task_id, []).append(x)
    out = []
    for c in sorted(cs, key=lambda c: c.started, reverse=True):
        r, done = c.root, c.done_at
        out.append(ChainOut(
            task_id=r.id, last_task_id=c.last.id, kind=c.kind, source_lang=r.source_lang,
            content=Trilingual(zh=c.last.content_zh, sr=c.last.content_sr, en=c.last.content_en),
            started_at=c.started, status=c.last.status, done_at=done,
            hours=round((done - c.started).total_seconds() / 3600, 1) if done else None,
            team_ids=list(dict.fromkeys(t.team_id for t in c.tasks)),
            logs=[LogBrief(content=Trilingual(zh=x.content_zh, sr=x.content_sr, en=x.content_en),
                           source_lang=x.source_lang, author=wn.get(x.worker_id) or un.get(x.created_by, ""),
                           recorded_at=x.recorded_at, shift_date=x.shift_date, shift_kind=x.shift_kind)
                  for t in c.tasks for x in by_task.get(t.id, [])],
        ))
    return out


HEAD = {
    "zh": ["设备编号", "名称", "区域", "故障维修", "计划检修", "巡查", "其他", "合计", "未完成", "超时未完成",
           "平均修好用时(小时)", "处理用时合计(小时)", "移交次数", "班次日志", "最近一次", f"{es.REPEAT_DAYS}天内最多故障", "反复故障"],
    "sr": ["Oznaka", "Naziv", "Lokacija", "Kvarovi", "Plan. održavanje", "Obilasci", "Ostalo", "Ukupno", "Otvoreno",
           "Kasni", "Prosečno do popravke (h)", "Ukupno sati rada", "Predaje", "Zapisi u dnevniku", "Poslednji put",
           f"Najviše kvarova za {es.REPEAT_DAYS} dana", "Ponavlja se"],
    "en": ["Code", "Name", "Area", "Breakdowns", "Planned maint.", "Inspections", "Other", "Total", "Open", "Overdue",
           "Avg. hours to fix", "Total work hours", "Handovers", "Log entries", "Last", f"Max breakdowns in {es.REPEAT_DAYS} days",
           "Recurring"],
}
YES = {"zh": "是", "sr": "da", "en": "yes"}
TITLE = {"zh": "设备统计", "sr": "Statistika opreme", "en": "Equipment statistics"}


@router.get("/xlsx")
def export_stats(start: date | None = None, end: date | None = None, lang: Lang = "zh", db: Session = Depends(get_db),
                 user: User = Depends(get_current_user), dept: int | None = Depends(get_dept)):
    _check(db, user)
    start, end = _range(start, end)
    rows, _idle = _stats(db, dept, start, end)
    tz = get_settings().tz
    wb = Workbook()
    ws = wb.active
    ws.title = TITLE[lang]
    ws.append([f"{TITLE[lang]}  {start} ~ {end}"])
    ws["A1"].font = Font(bold=True, size=13)
    ws.append(HEAD[lang])
    for c in ws[2]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="DDEBF7")
        c.alignment = Alignment(wrap_text=True, vertical="center")
    pick = lambda e, f: getattr(e, f"{f}_{lang}") or getattr(e, f"{f}_{e.source_lang}") or ""
    for r in rows:
        e = r.equipment
        ws.append([e.code, pick(e, "name"), pick(e, "area"), r.counts["fault"], r.counts["maintenance"],
                   r.counts["inspection"], r.counts["other"], r.total, r.open, r.overdue, r.avg_hours, r.work_hours,
                   r.handovers, r.logs, r.last_at.astimezone(tz).replace(tzinfo=None) if r.last_at else None,
                   r.repeat_max, YES[lang] if r.repeat else ""])
        if r.repeat:
            ws.cell(ws.max_row, len(HEAD[lang])).font = Font(bold=True, color="C00000")
    for i, w in enumerate([14, 28, 18] + [10] * 14, start=1):
        ws.column_dimensions[get_column_letter(i)].width = w
    ws.freeze_panes = "D3"
    buf = io.BytesIO()
    wb.save(buf)
    audit.log(db, user_id=user.id, action="export", entity="export", entity_id="equipment-stats",
              new={"start": str(start), "end": str(end), "lang": lang})
    db.commit()
    return StreamingResponse(io.BytesIO(buf.getvalue()),
                             media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f"attachment; filename=equipment-stats-{start}-{end}.xlsx"})
