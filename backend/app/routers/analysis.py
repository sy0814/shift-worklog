"""AI 工作量分析（仅管理员）。"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import analysis, audit, llm_config
from ..db import get_db
from ..models import AiReport, Team, User
from ..schemas import UTCDateTime
from ..security import require_admin

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
                end=r.end, team_id=r.team_id, lang=r.lang, status=r.status, model=r.model, finished_at=r.finished_at)


def _names(db: Session) -> dict:
    return dict(db.execute(select(User.id, User.full_name)).all())


@router.post("", response_model=ReportOut, status_code=201)
def create_report(body: ReportIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if body.end < body.start or (body.end - body.start).days >= MAX_DAYS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"range must be 1..{MAX_DAYS} days")
    if body.team_id is not None and db.get(Team, body.team_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "team not found")
    if not llm_config.current().configured:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "AI API not configured")
    if db.scalar(select(AiReport.id).where(AiReport.status.in_(("pending", "running")))):
        raise HTTPException(status.HTTP_409_CONFLICT, "another analysis is running")
    r = AiReport(created_by=admin.id, start=body.start, end=body.end, team_id=body.team_id, lang=body.lang,
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
                 _: User = Depends(require_admin)):
    names = _names(db)
    rows = db.scalars(select(AiReport).order_by(AiReport.id.desc()).limit(limit)).all()
    return [_brief(r, names) for r in rows]


@router.get("/{report_id}", response_model=ReportOut)
def get_report(report_id: int, db: Session = Depends(get_db), _: User = Depends(require_admin)):
    r = db.get(AiReport, report_id)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return ReportOut(**_brief(r, _names(db)), stats=r.stats, report_md=r.report_md, error=r.error, usage=r.usage)


@router.post("/{report_id}/retry", response_model=ReportBrief)
def retry_report(report_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    r = db.get(AiReport, report_id)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if r.status != "failed":
        raise HTTPException(status.HTTP_409_CONFLICT, "only failed reports can be retried")
    r.error = None
    audit.log(db, user_id=admin.id, action="retry", entity="ai_report", entity_id=r.id)
    db.commit()
    analysis.start_in_background(r.id)
    return _brief(r, _names(db))
