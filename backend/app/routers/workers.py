"""员工名册：所有人可查看，管理员维护。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import Team, User, Worker
from ..schemas import WorkerBulkCreate, WorkerCreate, WorkerOut, WorkerUpdate
from ..security import get_current_user, require_admin

router = APIRouter(prefix="/api/workers", tags=["workers"])


def _check(db: Session, team_id: int | None, employee_no: str | None, exclude_id: int | None = None):
    if team_id is not None and db.get(Team, team_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "team not found")
    if employee_no:
        q = select(Worker).where(Worker.employee_no == employee_no)
        if exclude_id:
            q = q.where(Worker.id != exclude_id)
        if db.scalar(q):
            raise HTTPException(status.HTTP_409_CONFLICT, "employee_no exists")


@router.get("", response_model=list[WorkerOut])
def list_workers(include_inactive: bool = False, db: Session = Depends(get_db),
                 _: User = Depends(get_current_user)):
    q = select(Worker).order_by(Worker.team_id, Worker.name)
    if not include_inactive:
        q = q.where(Worker.is_active.is_(True))
    return db.scalars(q).all()


@router.post("", response_model=WorkerOut, status_code=201)
def create_worker(body: WorkerCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    no = (body.employee_no or "").strip() or None
    _check(db, body.team_id, no)
    w = Worker(name=body.name.strip(), employee_no=no, team_id=body.team_id)
    db.add(w)
    db.flush()
    audit.log(db, user_id=admin.id, action="create", entity="worker", entity_id=w.id,
              new={"name": w.name, "employee_no": no, "team_id": w.team_id})
    db.commit()
    return w


@router.post("/bulk", response_model=list[WorkerOut], status_code=201)
def bulk_create(body: WorkerBulkCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """一次粘贴多个名字（每行一个）。"""
    _check(db, body.team_id, None)
    out = []
    for name in dict.fromkeys(n.strip() for n in body.names if n.strip()):
        w = Worker(name=name[:100], team_id=body.team_id)
        db.add(w)
        db.flush()
        audit.log(db, user_id=admin.id, action="create", entity="worker", entity_id=w.id,
                  new={"name": w.name, "team_id": w.team_id})
        out.append(w)
    db.commit()
    return out


@router.patch("/{worker_id}", response_model=WorkerOut)
def update_worker(worker_id: int, body: WorkerUpdate, db: Session = Depends(get_db),
                  admin: User = Depends(require_admin)):
    w = db.get(Worker, worker_id)
    if w is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    changes = body.model_dump(exclude_unset=True)
    if "employee_no" in changes:
        changes["employee_no"] = (changes["employee_no"] or "").strip() or None
    if "name" in changes:
        changes["name"] = changes["name"].strip()
    _check(db, changes.get("team_id", w.team_id), changes.get("employee_no"), exclude_id=w.id)
    audit.log_changes(db, w, changes, user_id=admin.id, entity="worker", entity_id=w.id)
    db.commit()
    return w
