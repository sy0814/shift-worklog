"""车间：导航页的列表（不需要登录）、新增 / 修改 / 删除（系统管理员）。"""

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, translation_service
from ..db import Base, get_db
from ..departments import all_departments
from ..models import Department, User
from ..schedule_service import load_schedule, local_now
from ..schemas import DepartmentOut
from ..security import require_admin

router = APIRouter(prefix="/api/departments", tags=["departments"])


class PortalDept(DepartmentOut):
    teams: int  # 有几个班组
    on_duty_team_ids: list[int]  # 此刻在班的班组（主班组在前）


class PortalOut(BaseModel):
    shift_kind: str  # 此刻是哪个班次
    departments: list[PortalDept]


@router.get("", response_model=PortalOut)
def portal(db: Session = Depends(get_db)):
    """导航页：所有车间（含停用的，前端只显示在用的）和此刻各车间在班的班组。不需要登录。"""
    sched = load_schedule(db)
    d, k = sched.shift_at(local_now())
    out = []
    for dep in all_departments(db):
        on = sched.teams_on(d, k, dep.id)
        on.sort(key=lambda t: not t.is_main)
        out.append(PortalDept(**DepartmentOut.model_validate(dep).model_dump(),
                              teams=sum(1 for t in sched.teams if t.dept == dep.id),
                              on_duty_team_ids=[t.id for t in on]))
    return PortalOut(shift_kind=k, departments=out)


class DepartmentIn(BaseModel):
    name_zh: str = Field(default="", max_length=100)
    name_sr: str = Field(default="", max_length=100)
    name_en: str = Field(default="", max_length=100)
    is_active: bool = True
    sort_order: int | None = None


def _fields(body: DepartmentIn) -> dict:
    names = {l: getattr(body, f"name_{l}").strip() for l in ("zh", "sr", "en")}
    if not any(names.values()):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "department name required")
    filled = translation_service.fill_names(names)  # 只填了一种语言：自动翻译其他的
    out = {f"name_{l}": translation_service.fit(filled[l], 100) for l in ("zh", "sr", "en")}
    out["is_active"] = body.is_active
    if body.sort_order is not None:
        out["sort_order"] = body.sort_order
    return out


@router.post("", response_model=DepartmentOut, status_code=201)
def create_department(body: DepartmentIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    f = _fields(body)
    n = (db.scalar(select(func.max(Department.id))) or 0) + 1
    code = f"D{n}"
    while db.scalar(select(Department.id).where(Department.code == code)):
        n += 1
        code = f"D{n}"
    f.setdefault("sort_order", (db.scalar(select(func.max(Department.sort_order))) or 0) + 1)
    dep = Department(code=code, **f)
    db.add(dep)
    db.flush()
    audit.log(db, user_id=admin.id, action="create", entity="department", entity_id=dep.id, new=f)
    db.commit()
    return dep


@router.put("/{dept_id}", response_model=DepartmentOut)
def update_department(dept_id: int, body: DepartmentIn, db: Session = Depends(get_db),
                      admin: User = Depends(require_admin)):
    dep = db.get(Department, dept_id)
    if dep is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    f = _fields(body)
    if not f["is_active"] and dep.is_active and \
            sum(1 for d in all_departments(db, active_only=True) if d.id != dep.id) == 0:
        raise HTTPException(status.HTTP_409_CONFLICT, "keep at least one active department")
    audit.log_changes(db, dep, f, user_id=admin.id, entity="department", entity_id=dep.id)
    db.commit()
    return dep


def _refs(db: Session, dept_id: int) -> int:
    n = 0
    for table in Base.metadata.sorted_tables:
        for col in table.columns:
            if any(fk.column.table.name == "departments" for fk in col.foreign_keys):
                n += db.scalar(select(func.count()).select_from(table).where(col == dept_id)) or 0
    return n


@router.delete("/{dept_id}", status_code=204)
def delete_department(dept_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """只能删除空车间（没有班组、员工、设备、巡查项……）；用过的请停用。"""
    dep = db.get(Department, dept_id)
    if dep is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if _refs(db, dept_id):
        raise HTTPException(status.HTTP_409_CONFLICT, "department in use; deactivate it instead")
    if len(all_departments(db)) <= 1:
        raise HTTPException(status.HTTP_409_CONFLICT, "keep at least one active department")
    audit.log(db, user_id=admin.id, action="delete", entity="department", entity_id=dept_id,
              old={"name_zh": dep.name_zh, "code": dep.code})
    db.delete(dep)
    db.commit()
