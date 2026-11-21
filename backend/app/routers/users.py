"""账号管理（仅管理员）。"""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import Team, User
from ..schemas import PasswordReset, UserCreate, UserOut, UserUpdate
from ..security import hash_password, require_admin

router = APIRouter(prefix="/api/users", tags=["users"])


def _check_team(db: Session, role: str, team_id: int | None) -> None:
    if role == "leader":
        if team_id is None or db.get(Team, team_id) is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "leader must belong to a team")


@router.get("", response_model=list[UserOut])
def list_users(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return db.scalars(select(User).order_by(User.id)).all()


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    if db.scalar(select(User).where(User.username == body.username)):
        raise HTTPException(status.HTTP_409_CONFLICT, "username exists")
    team_id = body.team_id if body.role == "leader" else None
    _check_team(db, body.role, team_id)
    u = User(username=body.username, password_hash=hash_password(body.password),
             full_name=body.full_name, role=body.role, team_id=team_id, lang=body.lang)
    db.add(u)
    db.flush()
    audit.log(db, user_id=admin.id, action="create", entity="user", entity_id=u.id,
              new={"username": u.username, "full_name": u.full_name, "role": u.role,
                   "team_id": u.team_id})
    db.commit()
    return u


@router.patch("/{user_id}", response_model=UserOut)
def update_user(user_id: int, body: UserUpdate, db: Session = Depends(get_db),
                admin: User = Depends(require_admin)):
    u = db.get(User, user_id)
    if u is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    changes = body.model_dump(exclude_unset=True)
    if u.id == admin.id and (changes.get("is_active") is False or changes.get("role") == "leader"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "cannot demote or disable yourself")
    role = changes.get("role", u.role)
    if role == "admin":
        changes["team_id"] = None
    _check_team(db, role, changes.get("team_id", u.team_id))
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
    audit.log(db, user_id=admin.id, action="reset_password", entity="user", entity_id=u.id)
    db.commit()
