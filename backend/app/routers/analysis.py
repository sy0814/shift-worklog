"""AI 工作量分析：系统管理员（全厂）、有「AI 工作量分析」权限的车间管理员（本车间）。"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import analysis, audit, departments, llm_config, permissions
from ..departments import get_dept
from ..db import get_db
from ..models import AiReport, Team, User
from ..schemas import UTCDateTime
from ..security import get_current_user

router = APIRouter(prefix="/api/analysis", tags=["analysis"])
MAX_DAYS = 93


class ReportIn(BaseModel):
    start: date
    end: date
    team_id: int | None = None
    lang: str = Field(default="zh", pattern="^(zh|sr|en)$")


class ReportBrief(BaseModel):
    id: int
    created_at: UTCDateTime
    created_by_name: str
    start: date
    end: date
    team_id: int | None
    department_id: int | None = None
    lang: str
    status: str
    model: str
    finished_at: UTCDateTime | None


class ReportOut(ReportBrief):
    stats: dict | None
    report_md: str | None
    error: str | None
    usage: dict | None


def _brief(r: AiReport, names: dict) -> dict:
    return dict(id=r.id, created_at=r.created_at, created_by_name=names.get(r.created_by, ""), start=r.start,
                end=r.end, team_id=r.team_id, department_id=r.department_id, lang=r.lang, status=r.status, model=r.model, finished_at=r.finished_at)


def _names(db: Session) -> dict:
    return dict(db.execute(select(User.id, User.full_name)).all())


def _who_ok(db: Session, user: User, dept: int | None) -> None:
    permissions.require(permissions.who(db, user).dept_ok("analysis", dept))


def _get(db: Session, user: User, report_id: int) -> AiReport:
    r = db.get(AiReport, report_id)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    dept = r.department_id or departments.dept_of_team(db, r.team_id)
    _who_ok(db, user, dept)
    return r


@router.post("", response_model=ReportOut, status_code=201)
def create_report(body: ReportIn, db: Session = Depends(get_db), admin: User = Depends(get_current_user),
                  dept: int | None = Depends(get_dept)):
    """分析当前车间（选了班组就只分析这个班组）。"""
    if body.end < body.start or (body.end - body.start).days >= MAX_DAYS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"range must be 1..{MAX_DAYS} days")
    team = db.get(Team, body.team_id) if body.team_id is not None else None
    if body.team_id is not None and team is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "team not found")
    dept = team.department_id if team else dept
    _who_ok(db, admin, dept)
    if not llm_config.current().configured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI API not configured")
    if db.scalar(select(AiReport.id).where(AiReport.status.in_(("pending", "running")))):
        raise HTTPException(status.HTTP_409_CONFLICT, "another analysis is running")
    r = AiReport(created_by=admin.id, start=body.start, end=body.end, team_id=body.team_id, department_id=dept,
                 lang=body.lang,
                 status="pending", model=llm_config.current().analysis_model)
    db.add(r)
    db.flush()
    audit.log(db, user_id=admin.id, action="create", entity="ai_report", entity_id=r.id,
              new=body.model_dump(mode="json"))
    db.commit()
    analysis.start_in_background(r.id)
    return ReportOut(**_brief(r, _names(db)), stats=None, report_md=None, error=None, usage=None)


@router.get("", response_model=list[ReportBrief])
def list_reports(limit: int = Query(default=30, le=200), db: Session = Depends(get_db),
                 user: User = Depends(get_current_user), dept: int | None = Depends(get_dept)):
    """当前车间的报告。"""
    _who_ok(db, user, dept)
    names = _names(db)
    rows = db.scalars(select(AiReport).where(AiReport.department_id == dept)
                      .order_by(AiReport.id.desc()).limit(limit)).all()
    return [_brief(r, names) for r in rows]


@router.get("/{report_id}", response_model=ReportOut)
def get_report(report_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    r = _get(db, user, report_id)
    return ReportOut(**_brief(r, _names(db)), stats=r.stats, report_md=r.report_md, error=r.error, usage=r.usage)


@router.post("/{report_id}/retry", response_model=ReportBrief)
def retry_report(report_id: int, db: Session = Depends(get_db), admin: User = Depends(get_current_user)):
    r = _get(db, admin, report_id)
    if r.status != "failed":
        raise HTTPException(status.HTTP_409_CONFLICT, "only failed reports can be retried")
    r.error = None
    audit.log(db, user_id=admin.id, action="retry", entity="ai_report", entity_id=r.id)
    db.commit()
    analysis.start_in_background(r.id)
    return _brief(r, _names(db))
