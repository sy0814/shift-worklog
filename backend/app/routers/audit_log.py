from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import AuditLog, User
from ..schemas import AuditOut
from ..security import require_admin

router = APIRouter(prefix="/api/audit", tags=["audit"])


@router.get("", response_model=list[AuditOut])
def list_audit(
    entity: str | None = None,
    entity_id: str | None = None,
    limit: int = Query(default=100, le=1000),
    offset: int = 0,
    db: Session = Depends(get_db),
    _: User = Depends(require_admin),
):
    q = select(AuditLog).order_by(AuditLog.id.desc())
    if entity:
        q = q.where(AuditLog.entity == entity)
    if entity_id:
        q = q.where(AuditLog.entity_id == entity_id)
    return db.scalars(q.limit(limit).offset(offset)).all()
