"""员工名册：所有人可查看；系统管理员维护全厂，有「员工名册」权限（worker.manage）的车间管理员维护本车间
（网页上逐格修改、加行、Excel 导入导出）。自定义列只有系统管理员能加减（全厂共用）。"""

import io
import re
from datetime import date, datetime, timezone
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import app_settings, audit, departments, permissions, worker_history
from ..departments import get_dept
from ..schedule_service import local_now
from ..db import get_db
from ..models import Department, Role, Team, User, Worker, WorkerField, WorkerSchedule, utcnow
from ..schemas import WorkerBulkCreate, WorkerCreate, WorkerOut, WorkerUpdate
from ..config import get_settings
from ..images import InvalidImage, process_avatar
from ..security import get_current_user, hash_password, require_admin, verify_avatar_token

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


def _manager(db: Session, user: User, dept_id: int | None) -> "permissions.Who":
    """能不能维护这个车间的名册（系统管理员：任何车间；车间管理员：本车间）。"""
    w = permissions.who(db, user)
    if not w.dept_ok("worker.manage", dept_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your department")
    return w


def _team_dept(db: Session, team_id: int | None, fallback: int | None) -> int | None:
    """员工属于哪个车间：有班组 = 班组的车间，否则 fallback。"""
    if team_id is not None:
        t = db.get(Team, team_id)
        if t is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "team not found")
        return t.department_id
    if fallback is not None and db.get(Department, fallback) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "department not found")
    return fallback


def _role_ok(db: Session, who: "permissions.Who", role_id: int | None) -> None:
    """车间管理员不能给人设「全厂」范围的角色（只有系统管理员 / 全厂范围的人能设）。"""
    if role_id is None or who.scope("worker.manage") == "all":
        return
    r = db.get(Role, role_id)
    if r is not None and "all" in (r.permissions or {}).values():
        raise HTTPException(status.HTTP_403_FORBIDDEN, "cannot assign a factory-wide role")


def _wide(db: Session, w: Worker) -> bool:
    """这个人的角色有没有「全厂」范围的权限（这种人只有全厂范围的管理者能管账号）。"""
    r = permissions.role_of(db, w)
    return r is not None and "all" in (r.permissions or {}).values()


def _clean_extra(db: Session, extra: dict[str, str], current: dict | None = None) -> dict:
    """合并自定义列的值：只接受存在的列；空字符串 = 删掉这一格。"""
    ids = {str(i) for i in db.scalars(select(WorkerField.id))}
    out = dict(current or {})
    for k, v in extra.items():
        if k not in ids:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, f"unknown column {k}")
        v = (v or "").strip()[:500]
        if v:
            out[k] = v
        else:
            out.pop(k, None)
    return out


def _set_extra(db: Session, w: Worker, new: dict, user_id: int, action: str = "update") -> bool:
    """写入自定义列的值，按列名逐格留痕（字段记成「[列名]」）。"""
    old = dict(w.extra or {})
    if old == new:
        return False
    labels = {str(f.id): f.label for f in db.scalars(select(WorkerField))}
    for k in sorted(set(old) | set(new)):
        if old.get(k) != new.get(k):
            audit.log(db, user_id=user_id, action=action, entity="worker", entity_id=w.id,
                      field=f"[{labels.get(k, k)}]", old=old.get(k), new=new.get(k))
    w.extra = new
    return True


# ---------------- 自定义列 ----------------
class FieldIO(BaseModel):
    label: str = Field(min_length=1, max_length=50)


class FieldOut(BaseModel):
    id: int
    label: str
    sort_order: int


@router.get("/fields", response_model=list[FieldOut])
def list_fields(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return [FieldOut(id=f.id, label=f.label, sort_order=f.sort_order)
            for f in db.scalars(select(WorkerField).order_by(WorkerField.sort_order, WorkerField.id))]


def _add_field(db: Session, label: str, user_id: int) -> WorkerField:
    label = label.strip()
    if db.scalar(select(WorkerField).where(WorkerField.label == label)):
        raise HTTPException(status.HTTP_409_CONFLICT, "column exists")
    f = WorkerField(label=label, sort_order=(db.scalar(select(func.max(WorkerField.sort_order))) or 0) + 1)
    db.add(f)
    db.flush()
    audit.log(db, user_id=user_id, action="create", entity="worker", entity_id=f"field:{f.id}", field="extra",
              new=label)
    return f


@router.post("/fields", response_model=FieldOut, status_code=201)
def add_field(body: FieldIO, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    f = _add_field(db, body.label, admin.id)
    db.commit()
    return FieldOut(id=f.id, label=f.label, sort_order=f.sort_order)


@router.put("/fields/{fid}", response_model=FieldOut)
def rename_field(fid: int, body: FieldIO, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    f = db.get(WorkerField, fid)
    if f is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    label = body.label.strip()
    if label != f.label:
        if db.scalar(select(WorkerField).where(WorkerField.label == label)):
            raise HTTPException(status.HTTP_409_CONFLICT, "column exists")
        audit.log(db, user_id=admin.id, action="update", entity="worker", entity_id=f"field:{f.id}", field="extra",
                  old=f.label, new=label)
        f.label = label
        db.commit()
    return FieldOut(id=f.id, label=f.label, sort_order=f.sort_order)


@router.delete("/fields/{fid}", status_code=204)
def delete_field(fid: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    """删除一列（连同这一列所有人的值；删除前的值记在留痕里）。"""
    f = db.get(WorkerField, fid)
    if f is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    key = str(f.id)
    values = {}
    for w in db.scalars(select(Worker)):
        if key in (w.extra or {}):
            values[w.name] = w.extra[key]
            w.extra = {k: v for k, v in w.extra.items() if k != key}
    audit.log(db, user_id=admin.id, action="delete", entity="worker", entity_id=f"field:{f.id}", field="extra",
              old={"label": f.label, "values": values})
    db.delete(f)
    db.commit()


@router.get("", response_model=list[WorkerOut])
def list_workers(include_inactive: bool = False, db: Session = Depends(get_db),
                 _: User = Depends(get_current_user)):
    q = select(Worker).order_by(Worker.team_id, Worker.name)
    if not include_inactive:
        q = q.where(Worker.is_active.is_(True))
    return db.scalars(q).all()


@router.post("", response_model=WorkerOut, status_code=201)
def create_worker(body: WorkerCreate, db: Session = Depends(get_db), admin: User = Depends(get_current_user),
                  dept: int | None = Depends(get_dept)):
    no = (body.employee_no or "").strip() or None
    _check(db, body.team_id, no)
    dept_id = _team_dept(db, body.team_id, body.department_id or dept)
    _manager(db, admin, dept_id)
    w = Worker(name=body.name.strip(), employee_no=no, team_id=body.team_id, department_id=dept_id,
               extra=_clean_extra(db, body.extra))
    db.add(w)
    db.flush()
    worker_history.ensure_baseline(db, w, w.team_id)
    audit.log(db, user_id=admin.id, action="create", entity="worker", entity_id=w.id,
              new={"name": w.name, "employee_no": no, "team_id": w.team_id, **({"extra": w.extra} if w.extra else {})})
    ensure_account(db, w, admin.id)
    db.commit()
    return w


@router.post("/bulk", response_model=list[WorkerOut], status_code=201)
def bulk_create(body: WorkerBulkCreate, db: Session = Depends(get_db), admin: User = Depends(get_current_user),
                dept: int | None = Depends(get_dept)):
    """一次粘贴多个名字（每行一个）。"""
    _check(db, body.team_id, None)
    dept_id = _team_dept(db, body.team_id, dept)
    _manager(db, admin, dept_id)
    out = []
    for name in dict.fromkeys(n.strip() for n in body.names if n.strip()):
        w = Worker(name=name[:100], team_id=body.team_id, department_id=dept_id)
        db.add(w)
        db.flush()
        worker_history.ensure_baseline(db, w, w.team_id)
        audit.log(db, user_id=admin.id, action="create", entity="worker", entity_id=w.id,
                  new={"name": w.name, "team_id": w.team_id})
        ensure_account(db, w, admin.id)
        out.append(w)
    db.commit()
    return out


@router.patch("/{worker_id}", response_model=WorkerOut)
def update_worker(worker_id: int, body: WorkerUpdate, db: Session = Depends(get_db),
                  admin: User = Depends(get_current_user)):
    w = db.get(Worker, worker_id)
    if w is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    who = _manager(db, admin, w.department_id)
    if _wide(db, w) and who.scope("worker.manage") != "all":
        raise HTTPException(status.HTTP_403_FORBIDDEN, "cannot edit a factory-wide account")
    changes = body.model_dump(exclude_unset=True)
    if "team_id" in changes or "department_id" in changes:  # 换到别的车间：那个车间也要能管
        new_dept = _team_dept(db, changes.get("team_id", w.team_id), changes.get("department_id") or w.department_id)
        _manager(db, admin, new_dept)
        changes["department_id"] = new_dept
        if new_dept == w.department_id:
            changes.pop("department_id")
    if "employee_no" in changes:
        changes["employee_no"] = (changes["employee_no"] or "").strip() or None
    if "name" in changes:
        changes["name"] = changes["name"].strip()
    extra = changes.pop("extra", None)
    if "role_id" in changes and changes["role_id"] is not None and db.get(Role, changes["role_id"]) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "role not found")
    if "role_id" in changes:
        _role_ok(db, who, changes["role_id"])
    _check(db, changes.get("team_id", w.team_id), changes.get("employee_no"), exclude_id=w.id)
    new_team = changes.pop("team_id", w.team_id)
    audit.log_changes(db, w, changes, user_id=admin.id, entity="worker", entity_id=w.id)
    if new_team != w.team_id:  # 换班组：从今天起生效，以前的出勤还按原班组算
        worker_history.change_team(db, w, w.team_id, new_team, admin.id, local_now().date())
    if extra is not None:
        _set_extra(db, w, _clean_extra(db, extra, w.extra), admin.id)
    worker_history.sync_account(db, w)
    if "role_id" in changes:
        _auto_username(db, w)
    db.commit()
    return w


def _auto_username(db: Session, w: Worker) -> None:
    """角色改成个人账号（班长等）时，自动生成的用户名 w<编号> 换成工号（工号可用且没人占用时）。"""
    u = db.scalar(select(User).where(User.worker_id == w.id))
    role = permissions.role_of(db, w)
    if u is None or role is None or role.login_mode != "password" or not re.fullmatch(r"w\d+", u.username):
        return
    no = w.employee_no or ""
    if re.fullmatch(r"[A-Za-z0-9_.-]{2,50}", no) and db.scalar(select(User.id).where(User.username == no)) is None:
        audit.log(db, user_id=None, action="update", entity="user", entity_id=u.id, field="username", old=u.username, new=no)
        u.username = no


# ---------------- 登录账号（名册里的人）----------------
def ensure_account(db: Session, w: Worker, actor_id: int | None) -> User | None:
    """新加的员工自动开账号，密码 = 「新员工默认密码」，第一次登录必须改。
    班组账号（成员）：点头像 + 这个密码；个人账号（班长等）：用户名 = 工号（没有或重复就用 w<编号>）。"""
    if db.scalar(select(User).where(User.worker_id == w.id)) is not None:
        return None
    role = permissions.role_of(db, w)
    mode = role.login_mode if role else "pin"
    username = f"w{w.id}"
    if mode == "password" and w.employee_no and re.fullmatch(r"[A-Za-z0-9_.-]{2,50}", w.employee_no) \
            and db.scalar(select(User.id).where(User.username == w.employee_no)) is None:
        username = w.employee_no
    u = User(username=username, password_hash=hash_password(app_settings.default_password(db)), full_name=w.name,
             role="staff", team_id=w.team_id, worker_id=w.id, lang="zh", is_active=w.is_active, must_change_password=True)
    db.add(u)
    db.flush()
    audit.log(db, user_id=actor_id, action="create", entity="user", entity_id=u.id,
              new={"worker": w.name, "username": u.username, "login_mode": mode, "default_password": True})
    return u


class AccountOut(BaseModel):
    user_id: int | None  # 还没开账号时为空
    username: str | None
    login_mode: str  # password（个人账号）/ pin（班组公共账号 + 个人密码），由角色决定
    is_active: bool
    locked: bool
    must_change_password: bool = False  # 还在用默认 / 别人设的密码
    last_login_at: datetime | None


class AccountIn(BaseModel):
    username: str | None = Field(default=None, min_length=2, max_length=50, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str | None = Field(default=None, min_length=4, max_length=100)  # 个人账号至少 6 位，班组账号至少 4 位
    is_active: bool | None = None


def _account_out(db: Session, w: Worker) -> AccountOut:
    from .auth import login_mode

    u = db.scalar(select(User).where(User.worker_id == w.id))
    role = permissions.role_of(db, w)
    mode = role.login_mode if role else "pin"
    if u is None:
        return AccountOut(user_id=None, username=None, login_mode=mode, is_active=False, locked=False, last_login_at=None)
    lk = u.locked_until
    if lk is not None and lk.tzinfo is None:
        lk = lk.replace(tzinfo=timezone.utc)
    return AccountOut(user_id=u.id, username=u.username if login_mode(db, u) == "password" else None, login_mode=mode,
                      is_active=u.is_active, locked=bool(lk and lk > utcnow()), last_login_at=u.last_login_at,
                      must_change_password=u.must_change_password)


def _can_manage_account(db: Session, user: User, w: Worker) -> bool:
    """系统管理员：任何人；车间管理员（员工名册权限）：本车间的人（全厂范围角色的人除外）；
    有「重设成员个人密码」权限的班长：本班组用班组账号登录的人。"""
    if user.role == "admin":
        return True
    who = permissions.who(db, user)
    if who.dept_ok("worker.manage", w.department_id) and (who.scope("worker.manage") == "all" or not _wide(db, w)):
        return True
    role = permissions.role_of(db, w)
    return (role is not None and role.login_mode == "pin" and who.team_ok("worker.pin", w.team_id))


def _can_rename_account(db: Session, user: User, w: Worker) -> bool:
    return user.role == "admin" or permissions.who(db, user).dept_ok("worker.manage", w.department_id)


@router.get("/{worker_id}/account", response_model=AccountOut)
def get_account(worker_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    w = db.get(Worker, worker_id)
    if w is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    permissions.require(_can_manage_account(db, user, w))
    return _account_out(db, w)


@router.put("/{worker_id}/account", response_model=AccountOut)
def put_account(worker_id: int, body: AccountIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """开账号 / 改用户名 / 重设密码 / 停用。个人账号要用户名 + 密码（≥6 位）；班组账号只要个人密码（≥4 位）。"""
    from .auth import check_secret

    w = db.get(Worker, worker_id)
    if w is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    permissions.require(_can_manage_account(db, user, w))
    role = permissions.role_of(db, w)
    mode = role.login_mode if role else "pin"
    u = db.scalar(select(User).where(User.worker_id == w.id))
    if mode == "password":
        if body.username and body.username != (u.username if u else None):
            if not _can_rename_account(db, user, w):
                raise HTTPException(status.HTTP_403_FORBIDDEN, "admin only")
            if db.scalar(select(User).where(User.username == body.username)):
                raise HTTPException(status.HTTP_409_CONFLICT, "username exists")
        if u is None and not body.username:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "username required")
    if u is None:
        if not body.password:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "password required")
        u = User(username=body.username if mode == "password" else f"w{w.id}", password_hash="!",
                 full_name=w.name, role="staff", team_id=w.team_id, worker_id=w.id, lang=user.lang)
        db.add(u)
        db.flush()
        audit.log(db, user_id=user.id, action="create", entity="user", entity_id=u.id,
                  new={"worker": w.name, "username": u.username, "login_mode": mode})
    elif mode == "password" and body.username and body.username != u.username:
        audit.log_changes(db, u, {"username": body.username}, user_id=user.id, entity="user", entity_id=u.id)
    if body.password:
        check_secret(db, u, body.password)
        u.password_hash = hash_password(body.password)
        u.failed_logins, u.locked_until = 0, None
        u.must_change_password = u.id != user.id  # 别人设的密码：登录后必须先改
        audit.log(db, user_id=user.id, action="reset_password", entity="user", entity_id=u.id)
    if body.is_active is not None and body.is_active != u.is_active:
        audit.log_changes(db, u, {"is_active": body.is_active and w.is_active}, user_id=user.id, entity="user",
                          entity_id=u.id)
    db.commit()
    return _account_out(db, w)


# ---------------- 头像 ----------------
def _can_edit_avatar(db: Session, user: User, w: Worker) -> bool:
    return permissions.who(db, user).team_ok("worker.avatar", w.team_id)


@router.post("/{worker_id}/avatar", response_model=WorkerOut)
async def upload_avatar(worker_id: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    """上传头像（管理员任何人；班长本班组的人）。"""
    w = db.get(Worker, worker_id)
    if w is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if not _can_edit_avatar(db, user, w):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your team's worker")
    data = await file.read(20 * 1024 * 1024 + 1)
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "file too large")
    root = Path(get_settings().upload_dir)
    try:
        rel = process_avatar(data, root)
    except InvalidImage:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "not a supported image")
    old = w.avatar_path
    w.avatar_path = rel
    audit.log(db, user_id=user.id, action="update", entity="worker", entity_id=w.id, field="avatar",
              old=old, new=rel)
    db.commit()
    return w


@router.delete("/{worker_id}/avatar", response_model=WorkerOut)
def delete_avatar(worker_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    w = db.get(Worker, worker_id)
    if w is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if not _can_edit_avatar(db, user, w):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your team's worker")
    if w.avatar_path:
        audit.log(db, user_id=user.id, action="update", entity="worker", entity_id=w.id, field="avatar",
                  old=w.avatar_path, new=None)
        w.avatar_path = None
        db.commit()
    return w


@router.get("/{worker_id}/avatar", include_in_schema=False)
def get_avatar(worker_id: int, t: str, db: Session = Depends(get_db)):
    w = db.get(Worker, worker_id)
    if w is None or not w.avatar_path or not verify_avatar_token(t, worker_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    path = Path(get_settings().upload_dir) / w.avatar_path
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return FileResponse(path, media_type="image/jpeg", headers={"Cache-Control": "private, max-age=43200"})


# ---------------- Excel 导入导出 ----------------
HEAD = {
    "zh": {"no": "工号", "name": "姓名", "team": "班组", "active": "在职", "yes": "是", "no_": "否", "sheet": "员工名册"},
    "sr": {"no": "Matični br.", "name": "Ime", "team": "Ekipa", "active": "Aktivan", "yes": "da", "no_": "ne", "sheet": "Radnici"},
    "en": {"no": "Employee no.", "name": "Name", "team": "Team", "active": "Active", "yes": "yes", "no_": "no", "sheet": "Workers"},
}
# 导入时认的表头写法（三种语言都认）
ALIASES = {
    "no": {"工号", "编号", "matični br.", "maticni br.", "matični broj", "br.", "employee no.", "employee no", "no.", "id"},
    "name": {"姓名", "名字", "ime", "ime i prezime", "name"},
    "team": {"班组", "班", "ekipa", "smena", "team"},
    "active": {"在职", "启用", "aktivan", "active"},
}
YES = {"是", "在职", "1", "y", "yes", "true", "da", "√", "✓"}
NO = {"否", "离职", "停用", "0", "n", "no", "false", "ne", "×"}


def _team_lookup(db: Session, dept_id: int | None) -> dict[str, int]:
    """班组名 → id（只认这个车间的班组：各车间可能都有「1班」）。"""
    out = {}
    for t in db.scalars(select(Team).where(Team.department_id == dept_id)):
        for n in (t.code, t.name_zh, t.name_sr, t.name_en):
            if n:
                out[str(n).strip().lower()] = t.id
    return out


@router.get("/export.xlsx", include_in_schema=False)
def export_workers(lang: str = Query(default="zh", pattern="^(zh|sr|en)$"), include_inactive: bool = True,
                   db: Session = Depends(get_db), admin: User = Depends(get_current_user),
                   dept: int | None = Depends(get_dept)):
    """导出当前车间的名册。"""
    _manager(db, admin, dept)
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    H = HEAD[lang]
    fields = list(db.scalars(select(WorkerField).order_by(WorkerField.sort_order, WorkerField.id)))
    teams = {t.id: getattr(t, f"name_{lang}") for t in db.scalars(select(Team))}
    q = select(Worker).where(Worker.department_id == dept).order_by(Worker.team_id, Worker.name)
    if not include_inactive:
        q = q.where(Worker.is_active.is_(True))
    wb = Workbook()
    ws = wb.active
    ws.title = H["sheet"]
    ws.append([H["no"], H["name"], H["team"], H["active"], *[f.label for f in fields]])
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="DDEBF7")
    for w in db.scalars(q):
        ws.append([w.employee_no or "", w.name, teams.get(w.team_id, ""), H["yes"] if w.is_active else H["no_"],
                   *[(w.extra or {}).get(str(f.id), "") for f in fields]])
    for col, width in zip("ABCD", (14, 20, 10, 8)):
        ws.column_dimensions[col].width = width
    ws.freeze_panes = "C2"
    buf = io.BytesIO()
    wb.save(buf)
    audit.log(db, user_id=admin.id, action="export", entity="worker", entity_id="roster", new={"lang": lang})
    db.commit()
    buf.seek(0)
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": 'attachment; filename="workers.xlsx"'})


class ImportResult(BaseModel):
    created: int
    updated: int
    unchanged: int
    columns_added: list[str]
    errors: list[str]


@router.post("/import", response_model=ImportResult)
async def import_workers(file: UploadFile = File(...), dry_run: bool = False, db: Session = Depends(get_db),
                         admin: User = Depends(get_current_user), dept: int | None = Depends(get_dept)):
    """导入当前车间的员工名册：第一行是表头。按工号匹配（没有工号按本车间的姓名，重名报错），已有的更新、没有的新建；
    班组按本车间的班组名认；不认识的表头当作自定义列（没有就自动加上，只有系统管理员能加列）。
    整个文件先检查，有一行错就全不导入。不会删除表里没有的人。工号是别的车间的人时报错（换车间请在名册里改班组）。"""
    from openpyxl import load_workbook

    who = _manager(db, admin, dept)
    data = await file.read(10 * 1024 * 1024 + 1)
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "file too large")
    try:
        wb = load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "not an .xlsx file")
    rows = [list(r) for r in wb.active.iter_rows(values_only=True)]
    rows = [r for r in rows if any(c not in (None, "") for c in r)]
    if not rows:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty file")

    def s(v) -> str:
        if v is None:
            return ""
        if isinstance(v, float) and v.is_integer():
            v = int(v)
        return str(v).strip()

    header = [s(h) for h in rows[0]]
    cols: dict[str, int] = {}
    custom: dict[int, str] = {}  # 列号 → 自定义列名
    for i, h in enumerate(header):
        if not h:
            continue
        key = next((k for k, al in ALIASES.items() if h.lower() in al), None)
        if key and key not in cols:
            cols[key] = i
        else:
            custom[i] = h[:50]
    if "name" not in cols:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "missing column: name / 姓名 / Ime")

    teams = _team_lookup(db, dept)
    existing = list(db.scalars(select(Worker)))
    by_no = {w.employee_no: w for w in existing if w.employee_no}
    by_name: dict[str, list[Worker]] = {}
    for w in existing:
        if w.department_id == dept:
            by_name.setdefault(w.name, []).append(w)
    fields = {f.label: f for f in db.scalars(select(WorkerField))}

    errors, plan, seen_no = [], [], set()
    for n, r in enumerate(rows[1:], start=2):
        get = lambda k: s(r[cols[k]]) if k in cols and cols[k] < len(r) else ""
        name, no = get("name"), get("no")
        if not name:
            errors.append(f"{n}: name empty")
            continue
        if no and no in seen_no:
            errors.append(f"{n}: duplicate employee no. {no}")
            continue
        seen_no.add(no) if no else None
        team_id = None
        if "team" in cols:
            t = get("team")
            if t:
                team_id = teams.get(t.lower())
                if team_id is None:
                    errors.append(f"{n}: unknown team {t}")
                    continue
        active = None
        if "active" in cols and get("active"):
            a = get("active").lower()
            active = True if a in YES else False if a in NO else None
            if active is None:
                errors.append(f"{n}: active? {get('active')}")
                continue
        target = by_no.get(no) if no else None
        if target is None:
            same = by_name.get(name, [])
            if len(same) > 1:
                errors.append(f"{n}: several workers named {name}, add employee no.")
                continue
            target = same[0] if same and (not no or not same[0].employee_no) else None
        if target is not None and target.department_id != dept:
            errors.append(f"{n}: {no} belongs to another department")
            continue
        extra = {custom[i]: s(r[i]) if i < len(r) else "" for i in custom}
        plan.append((target, name, no or None, team_id, active, extra))
    if errors:
        return ImportResult(created=0, updated=0, unchanged=0, columns_added=[], errors=errors)

    added = [lbl for lbl in dict.fromkeys(custom.values()) if lbl not in fields]
    if added and not who.is_admin:
        return ImportResult(created=0, updated=0, unchanged=0, columns_added=[],
                            errors=[f"unknown column: {', '.join(added)}"])
    if dry_run:
        return ImportResult(created=sum(1 for p in plan if p[0] is None), updated=sum(1 for p in plan if p[0]),
                            unchanged=0, columns_added=added, errors=[])
    for lbl in added:
        fields[lbl] = _add_field(db, lbl, admin.id)
    created = updated = unchanged = 0
    for target, name, no, team_id, active, extra in plan:
        ex = {str(fields[k].id): v for k, v in extra.items()}
        if target is None:
            w = Worker(name=name, employee_no=no, team_id=team_id, department_id=dept,
                       is_active=True if active is None else active, extra={k: v for k, v in ex.items() if v})
            db.add(w)
            db.flush()
            worker_history.ensure_baseline(db, w, w.team_id)
            ensure_account(db, w, admin.id)
            audit.log(db, user_id=admin.id, action="import", entity="worker", entity_id=w.id,
                      new={"name": name, "employee_no": no, "team_id": team_id})
            created += 1
            continue
        changes = {"name": name}
        if no:
            changes["employee_no"] = no
        if active is not None:
            changes["is_active"] = active
        new_extra = dict(target.extra or {})
        for k, v in ex.items():
            if v:
                new_extra[k] = v
            else:
                new_extra.pop(k, None)
        a = audit.log_changes(db, target, changes, user_id=admin.id, entity="worker", entity_id=target.id,
                              action="import")
        if "team" in cols and team_id != target.team_id:  # 换班组：从今天起生效
            worker_history.change_team(db, target, target.team_id, team_id, admin.id, local_now().date())
            a = True
        b = _set_extra(db, target, new_extra, admin.id, action="import")
        if a or b:
            updated += 1
        else:
            unchanged += 1
    db.commit()
    return ImportResult(created=created, updated=updated, unchanged=unchanged, columns_added=added, errors=[])


# ---------------- 班组 / 个人排班变更记录（管理员）----------------
class ScheduleEntryOut(BaseModel):
    effective_from: date
    team_id: int | None
    pattern: list[str] | None  # 空 = 跟班组排班
    cycle_start: date | None
    holiday_off: bool
    note: str


class ScheduleEntryIn(BaseModel):
    effective_from: date
    team_id: int | None = None
    personal: bool = False  # True = 按个人循环；False = 跟班组排班
    pattern: list[str] | None = None
    cycle_start: date | None = None
    holiday_off: bool = False
    note: str = Field(default="", max_length=200)


def _entries(db: Session, worker_id: int) -> list[ScheduleEntryOut]:
    rows = db.scalars(select(WorkerSchedule).where(WorkerSchedule.worker_id == worker_id)
                      .order_by(WorkerSchedule.effective_from)).all()
    return [ScheduleEntryOut(effective_from=r.effective_from, team_id=r.team_id, pattern=r.pattern,
                             cycle_start=r.cycle_start, holiday_off=r.holiday_off, note=r.note) for r in rows]


@router.get("/{worker_id}/schedule", response_model=list[ScheduleEntryOut])
def get_schedule(worker_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    w = db.get(Worker, worker_id)
    if w is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    worker_history.ensure_baseline(db, w, w.team_id)
    db.commit()
    return _entries(db, worker_id)


@router.put("/{worker_id}/schedule", response_model=list[ScheduleEntryOut])
def put_schedule(worker_id: int, body: ScheduleEntryIn, db: Session = Depends(get_db),
                 admin: User = Depends(get_current_user)):
    """从某天起：属于哪个班组、跟班组排班还是按个人循环（例如每人休息日不同的一周排班）。
    同一天已有记录就覆盖。以前的出勤不受影响。"""
    from .schedule import _night_start, check_cycle
    from ..shifts import Cycle

    w = db.get(Worker, worker_id)
    if w is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    _manager(db, admin, w.department_id)
    _manager(db, admin, _team_dept(db, body.team_id, w.department_id))
    cycle = None
    if body.personal:
        cycle = Cycle(tuple(check_cycle(body.pattern, body.cycle_start, _night_start(db))), body.cycle_start, body.holiday_off)
    elif body.team_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "choose a team or a personal cycle")
    worker_history.record(db, w, body.effective_from, body.team_id, cycle, admin.id, body.note,
                          today=local_now().date())
    db.commit()
    return _entries(db, worker_id)


@router.delete("/{worker_id}/schedule/{effective_from}", response_model=list[ScheduleEntryOut])
def delete_schedule(worker_id: int, effective_from: date, db: Session = Depends(get_db),
                    admin: User = Depends(get_current_user)):
    """删掉某一次变更（最早那条不能删）。"""
    w = db.get(Worker, worker_id)
    if w is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    _manager(db, admin, w.department_id)
    if not worker_history.remove(db, w, effective_from, admin.id, local_now().date()):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "cannot delete this entry")
    db.commit()
    return _entries(db, worker_id)


class OpenAllOut(BaseModel):
    created: int
    password: str


@router.post("/accounts/open-all", response_model=OpenAllOut)
def open_all_accounts(db: Session = Depends(get_db), admin: User = Depends(get_current_user),
                      dept: int | None = Depends(get_dept)):
    """给当前车间名册里还没有账号的在职员工都开账号（默认密码，第一次登录必须改）。"""
    _manager(db, admin, dept)
    n = 0
    for w in db.scalars(select(Worker).where(Worker.is_active.is_(True), Worker.department_id == dept)):
        if ensure_account(db, w, admin.id) is not None:
            n += 1
    db.commit()
    return OpenAllOut(created=n, password=app_settings.default_password(db))
