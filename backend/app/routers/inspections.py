"""定期巡查项管理：查看（所有人）、增删改 / 预览 / 立即派发（管理员）。"""

from datetime import date, datetime, time

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .. import audit, inspection_service, translation_service
from ..db import get_db
from ..inspection_schedule import Rule, assignment, upcoming
from ..models import InspectionRun, InspectionTemplate, Team, User, Worker, utcnow
from ..schedule_service import load_schedule
from ..schemas import UTCDateTime
from ..security import get_current_user, require_admin

router = APIRouter(prefix="/api/inspections", tags=["inspections"])


class InspectionIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    content: str = Field(min_length=1, max_length=2000)
    lang: str = Field(default="zh", pattern="^(zh|sr|en)$")
    enabled: bool = True
    kind: str = Field(pattern="^(daily|weekly|monthly|shift)$")
    at_time: time = time(8, 0)
    every_n: int = Field(default=1, ge=1, le=365)
    weekdays: list[int] = Field(default_factory=list)
    month_days: list[int] = Field(default_factory=list)
    shift_kinds: list[str] = Field(default_factory=list)
    start_date: date | None = None
    assign: str = Field(default="on_duty", pattern="^(on_duty|fixed)$")
    team_id: int | None = None
    worker_ids: list[int] = Field(default_factory=list, max_length=50)


class InspectionOut(InspectionIn):
    id: int
    start_date: date
    next_run_at: UTCDateTime | None
    last_run_at: UTCDateTime | None
    runs: int
    updated_at: UTCDateTime


class Occurrence(BaseModel):
    at: datetime  # 工厂本地时间
    team_id: int | None
    shift_date: date
    shift_kind: str


class RunOut(BaseModel):
    id: int
    occurrence_at: UTCDateTime
    status: str
    task_id: int | None
    team_id: int | None
    note: str
    created_at: UTCDateTime


def _validate(db: Session, b: InspectionIn) -> dict:
    d = b.model_dump()
    d["name"], d["content"] = b.name.strip(), b.content.strip()
    d["start_date"] = b.start_date or date.today()
    if b.kind == "weekly":
        if not b.weekdays or any(not 0 <= x <= 6 for x in b.weekdays):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "weekdays required (0=Mon..6=Sun)")
        d["weekdays"] = sorted(set(b.weekdays))
    if b.kind == "monthly":
        if not b.month_days or any(not 1 <= x <= 31 for x in b.month_days):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "month_days required (1..31)")
        d["month_days"] = sorted(set(b.month_days))
    if b.kind == "shift":
        if not b.shift_kinds or any(k not in ("day", "middle", "night") for k in b.shift_kinds):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "shift_kinds required (day/middle/night)")
        d["shift_kinds"] = [k for k in ("day", "middle", "night") if k in b.shift_kinds]
    if b.assign == "fixed":
        if b.team_id is None or db.get(Team, b.team_id) is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "team_id required for a fixed team")
        if b.worker_ids and db.scalar(select(func.count()).select_from(Worker).where(Worker.id.in_(b.worker_ids))) != len(set(b.worker_ids)):
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown worker")
    else:
        d["team_id"], d["worker_ids"] = None, []  # 在班班组每次不同，不能预设人员
    return d


def _out(db: Session, t: InspectionTemplate) -> InspectionOut:
    n = db.scalar(select(func.count()).select_from(InspectionRun).where(InspectionRun.template_id == t.id))
    return InspectionOut(
        id=t.id, name=t.name, content=t.content, lang=t.lang, enabled=t.enabled, kind=t.kind, at_time=t.at_time,
        every_n=t.every_n, weekdays=t.weekdays or [], month_days=t.month_days or [], shift_kinds=t.shift_kinds or [],
        start_date=t.start_date, assign=t.assign, team_id=t.team_id, worker_ids=t.worker_ids or [],
        next_run_at=t.next_run_at, last_run_at=t.last_run_at, runs=n, updated_at=t.updated_at)


def _get(db: Session, iid: int) -> InspectionTemplate:
    t = db.get(InspectionTemplate, iid)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return t


@router.get("", response_model=list[InspectionOut])
def list_inspections(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return [_out(db, t) for t in db.scalars(select(InspectionTemplate).order_by(InspectionTemplate.id))]


@router.post("/preview", response_model=list[Occurrence])
def preview(body: InspectionIn, count: int = Query(default=5, le=20), db: Session = Depends(get_db),
            _: User = Depends(require_admin)):
    """按表单里的设置（不保存）算出接下来几次的时间和派给谁。"""
    d = _validate(db, body)
    rule = Rule(kind=d["kind"], at_time=d["at_time"], every_n=d["every_n"], weekdays=d["weekdays"],
                month_days=d["month_days"], shift_kinds=d["shift_kinds"], start_date=d["start_date"],
                assign=d["assign"], team_id=d["team_id"])
    sched = load_schedule(db)
    out = []
    for occ in upcoming(rule, inspection_service.to_local(utcnow()), sched, count):
        team, sd, sk = assignment(rule, occ, sched)
        out.append(Occurrence(at=occ, team_id=team.id if team else None, shift_date=sd, shift_kind=sk))
    return out


@router.post("", response_model=InspectionOut, status_code=201)
def create(body: InspectionIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    d = _validate(db, body)
    t = InspectionTemplate(**d, created_by=admin.id, updated_by=admin.id, created_at=utcnow(), updated_at=utcnow())
    db.add(t)
    db.flush()
    inspection_service.schedule_next(db, t)
    audit.log(db, user_id=admin.id, action="create", entity="inspection", entity_id=t.id,
              new=body.model_dump(mode="json"))
    db.commit()
    return _out(db, t)


@router.put("/{iid}", response_model=InspectionOut)
def update(iid: int, body: InspectionIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    t = _get(db, iid)
    d = _validate(db, body)
    if audit.log_changes(db, t, d, user_id=admin.id, entity="inspection", entity_id=t.id):
        t.updated_by, t.updated_at = admin.id, utcnow()
    inspection_service.schedule_next(db, t)  # 改了规则就从现在起重新算
    db.commit()
    return _out(db, t)


@router.delete("/{iid}", status_code=204)
def delete(iid: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    t = _get(db, iid)
    if db.scalar(select(InspectionRun.id).where(InspectionRun.template_id == t.id).limit(1)):
        raise HTTPException(status.HTTP_409_CONFLICT, "already has runs; disable it instead")
    audit.log(db, user_id=admin.id, action="delete", entity="inspection", entity_id=t.id, old={"name": t.name})
    db.delete(t)
    db.commit()


@router.post("/{iid}/run-now", response_model=RunOut)
def run_now(iid: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """立即派发一次（不影响正常周期）。"""
    t = _get(db, iid)
    # 手动派发用精确到微秒的时间，连点两次也不会和「同一次不能派两遍」的规则冲突
    run = inspection_service.create_task(db, t, inspection_service.to_local(utcnow()),
                                         run_status="manual", user_id=admin.id)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "dispatched just now, try again")
    if run.task_id:
        translation_service.enqueue(run.task_id)
    return RunOut.model_validate(run, from_attributes=True)


@router.get("/{iid}/runs", response_model=list[RunOut])
def runs(iid: int, limit: int = Query(default=50, le=500), db: Session = Depends(get_db),
         _: User = Depends(get_current_user)):
    _get(db, iid)
    rows = db.scalars(select(InspectionRun).where(InspectionRun.template_id == iid)
                      .order_by(InspectionRun.occurrence_at.desc()).limit(limit)).all()
    return [RunOut.model_validate(r, from_attributes=True) for r in rows]
