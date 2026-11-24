"""角色权限页（管理员）：增删改角色，勾选每个角色能做什么、范围、登录方式、首页是否单独显示。"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import Role, User, Worker
from ..permissions import PERMS, normalize
from ..security import get_current_user, require_admin

router = APIRouter(prefix="/api/roles", tags=["roles"])


class RoleIn(BaseModel):
    name_zh: str = Field(default="", max_length=50)
    name_sr: str = Field(default="", max_length=50)
    name_en: str = Field(default="", max_length=50)
    permissions: dict[str, str] = {}
    login_mode: str = Field(default="pin", pattern="^(password|pin)$")
    show_on_top: bool = False


class RoleOut(BaseModel):
    id: int
    code: str
    name_zh: str
    name_sr: str
    name_en: str
    permissions: dict[str, str]
    login_mode: str
    show_on_top: bool
    sort_order: int
    is_builtin: bool
    people: int  # 名册里有多少人是这个角色


class PermDef(BaseModel):
    key: str
    scopes: list[str]


def _out(db: Session, r: Role) -> RoleOut:
    q = select(func.count()).select_from(Worker).where(Worker.is_active.is_(True))
    if r.code == "member":
        q = q.where((Worker.role_id == r.id) | Worker.role_id.is_(None))
    else:
        q = q.where(Worker.role_id == r.id)
    return RoleOut(id=r.id, code=r.code, name_zh=r.name_zh, name_sr=r.name_sr, name_en=r.name_en,
                   permissions=normalize(r.permissions or {}), login_mode=r.login_mode, show_on_top=r.show_on_top,
                   sort_order=r.sort_order, is_builtin=r.is_builtin, people=db.scalar(q) or 0)


@router.get("/perms", response_model=list[PermDef])
def perm_defs(_: User = Depends(get_current_user)):
    """所有权限和每个权限可选的范围（页面按这个画表格）。"""
    return [PermDef(key=k, scopes=list(v)) for k, v in PERMS.items()]


@router.get("", response_model=list[RoleOut])
def list_roles(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return [_out(db, r) for r in db.scalars(select(Role).order_by(Role.sort_order, Role.id))]


def _fields(body: RoleIn) -> dict:
    names = {k: getattr(body, k).strip() for k in ("name_zh", "name_sr", "name_en")}
    first = next((v for v in names.values() if v), "")
    if not first:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "role name required")
    names = {k: v or first for k, v in names.items()}
    return {**names, "permissions": normalize(body.permissions), "login_mode": body.login_mode,
            "show_on_top": body.show_on_top}


@router.post("", response_model=RoleOut, status_code=201)
def create_role(body: RoleIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    d = _fields(body)
    n = (db.scalar(select(func.max(Role.id))) or 0) + 1
    r = Role(code=f"r{n}", sort_order=(db.scalar(select(func.max(Role.sort_order))) or 0) + 1, is_builtin=False, **d)
    db.add(r)
    db.flush()
    audit.log(db, user_id=admin.id, action="create", entity="role", entity_id=r.id, new=d)
    db.commit()
    return _out(db, r)


@router.put("/{role_id}", response_model=RoleOut)
def update_role(role_id: int, body: RoleIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    r = db.get(Role, role_id)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    d = _fields(body)
    old_perms = normalize(r.permissions or {})
    perms = d.pop("permissions")
    audit.log_changes(db, r, d, user_id=admin.id, entity="role", entity_id=r.id)
    for k in PERMS:  # 权限逐项留痕：「班长 task.edit: team → self」
        if old_perms.get(k) != perms.get(k):
            audit.log(db, user_id=admin.id, action="update", entity="role", entity_id=r.id, field=f"perm:{k}",
                      old=old_perms.get(k), new=perms.get(k))
    r.permissions = perms
    db.commit()
    return _out(db, r)


@router.delete("/{role_id}", status_code=204)
def delete_role(role_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    r = db.get(Role, role_id)
    if r is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if r.is_builtin:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "built-in role cannot be deleted")
    if db.scalar(select(func.count()).select_from(Worker).where(Worker.role_id == r.id)):
        raise HTTPException(status.HTTP_409_CONFLICT, "role in use")
    audit.log(db, user_id=admin.id, action="delete", entity="role", entity_id=r.id, old={"name_zh": r.name_zh})
    db.delete(r)
    db.commit()
