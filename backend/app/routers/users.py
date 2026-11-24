"""账号管理（仅管理员）：列出所有账号；新建系统管理员账号；停用 / 重设密码 / 解锁 / 改关联的名册人员。
名册里的人（班长、成员等）的账号在「员工名册 → 账号」里开。"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import User, Worker
from ..schemas import PasswordReset, UserCreate, UserOut, UserUpdate
from ..security import hash_password, require_admin

router = APIRouter(prefix="/api/users", tags=["users"])


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return db.scalars(select(User).order_by(User.role, User.team_id, User.username)).all()


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """新建系统管理员账号。"""
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(status.HTTP_409_CONFLICT, "username exists")
    u = User(username=body.username, password_hash=hash_password(body.password),
             full_name=body.full_name, role="admin", lang=body.lang)
    db.add(u)
    db.flush()
    audit.log(db, user_id=admin.id, action="create", entity="user", entity_id=u.id,
              new={"username": u.username, "full_name": u.full_name, "role": u.role})
    db.commit()
    return u


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, db: Session = Depends(get_db),
                admin: User = Depends(require_admin)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    changes = body.model_dump(exclude_unset=True)
    if u.id == admin.id and changes.get("is_active") is False:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "cannot demote or disable yourself")
    if u.worker_id:
        changes.pop("full_name", None)  # 名字以名册为准
    audit.log_changes(db, u, changes, user_id=admin.id, entity="user", entity_id=u.id)
    db.commit()
    return u


@router.post("/{user_id}/reset-password", status_code=204)
def reset_password(user_id: int, body: PasswordReset, db: Session = Depends(get_db),
                   admin: User = Depends(require_admin)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    u.password_hash = hash_password(body.password)
    u.failed_logins, u.locked_until = 0, None
    audit.log(db, user_id=admin.id, action="reset_password", entity="user", entity_id=u.id)
    db.commit()


@router.post("/{user_id}/unlock", status_code=204)
def unlock(user_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    u.failed_logins, u.locked_until = 0, None
    audit.log(db, user_id=admin.id, action="unlock", entity="user", entity_id=u.id)
    db.commit()


class Relink(BaseModel):
    worker_id: int


@router.put("/{user_id}/worker", response_model=UserOut)
def relink(user_id: int, body: Relink, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """把账号改关联到名册里的另一个人（升级时自动建的名册记录不对时用；原来那条名册记录请自行停用）。"""
    u = db.get(User, user_id)
    w = db.get(Worker, body.worker_id)
    if u is None or w is None or u.role == "admin":
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    other = db.scalar(select(User).where(User.worker_id == w.id))
    if other is not None and other.id != u.id:
        raise HTTPException(status.HTTP_409_CONFLICT, "worker already has an account")
    old = u.worker_id
    u.worker_id, u.full_name, u.team_id = w.id, w.name, w.team_id
    audit.log(db, user_id=admin.id, action="update", entity="user", entity_id=u.id, field="worker_id",
              old=old, new=w.id)
    db.commit()
    return u
