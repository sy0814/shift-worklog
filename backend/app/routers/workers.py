"""员工名册：所有人可查看，管理员维护（网页上逐格修改、加行加列、Excel 导入导出）。"""

import io
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit
from ..db import get_db
from ..models import Team, User, Worker, WorkerField
from ..schemas import WorkerBulkCreate, WorkerCreate, WorkerOut, WorkerUpdate
from ..config import get_settings
from ..images import InvalidImage, process_avatar
from ..security import get_current_user, require_admin, verify_avatar_token

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
def create_worker(body: WorkerCreate, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    no = (body.employee_no or "").strip() or None
    _check(db, body.team_id, no)
    w = Worker(name=body.name.strip(), employee_no=no, team_id=body.team_id, extra=_clean_extra(db, body.extra))
    db.add(w)
    db.flush()
    audit.log(db, user_id=admin.id, action="create", entity="worker", entity_id=w.id,
              new={"name": w.name, "employee_no": no, "team_id": w.team_id, **({"extra": w.extra} if w.extra else {})})
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
    extra = changes.pop("extra", None)
    _check(db, changes.get("team_id", w.team_id), changes.get("employee_no"), exclude_id=w.id)
    audit.log_changes(db, w, changes, user_id=admin.id, entity="worker", entity_id=w.id)
    if extra is not None:
        _set_extra(db, w, _clean_extra(db, extra, w.extra), admin.id)
    db.commit()
    return w


# ---------------- 头像 ----------------
def _can_edit_avatar(user: User, w: Worker) -> bool:
    return user.role == "admin" or (w.team_id is not None and w.team_id == user.team_id)


@router.post("/{worker_id}/avatar", response_model=WorkerOut)
async def upload_avatar(worker_id: int, file: UploadFile = File(...), db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    """上传头像（管理员任何人；班长本班组的人）。"""
    w = db.get(Worker, worker_id)
    if w is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if not _can_edit_avatar(user, w):
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
    if not _can_edit_avatar(user, w):
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


def _team_lookup(db: Session) -> dict[str, int]:
    out = {}
    for t in db.scalars(select(Team)):
        for n in (t.code, t.name_zh, t.name_sr, t.name_en):
            if n:
                out[str(n).strip().lower()] = t.id
    return out


@router.get("/export.xlsx", include_in_schema=False)
def export_workers(lang: str = Query(default="zh", pattern="^(zh|sr|en)$"), include_inactive: bool = True,
                   db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill

    H = HEAD[lang]
    fields = list(db.scalars(select(WorkerField).order_by(WorkerField.sort_order, WorkerField.id)))
    teams = {t.id: getattr(t, f"name_{lang}") for t in db.scalars(select(Team))}
    q = select(Worker).order_by(Worker.team_id, Worker.name)
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
                         admin: User = Depends(require_admin)):
    """导入员工名册：第一行是表头。按工号匹配（没有工号按姓名，重名报错），已有的更新、没有的新建；
    不认识的表头当作自定义列（没有就自动加上）。整个文件先检查，有一行错就全不导入。不会删除表里没有的人。"""
    from openpyxl import load_workbook

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

    teams = _team_lookup(db)
    existing = list(db.scalars(select(Worker)))
    by_no = {w.employee_no: w for w in existing if w.employee_no}
    by_name: dict[str, list[Worker]] = {}
    for w in existing:
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
        extra = {custom[i]: s(r[i]) if i < len(r) else "" for i in custom}
        plan.append((target, name, no or None, team_id, active, extra))
    if errors:
        return ImportResult(created=0, updated=0, unchanged=0, columns_added=[], errors=errors)

    added = [lbl for lbl in dict.fromkeys(custom.values()) if lbl not in fields]
    if dry_run:
        return ImportResult(created=sum(1 for p in plan if p[0] is None), updated=sum(1 for p in plan if p[0]),
                            unchanged=0, columns_added=added, errors=[])
    for lbl in added:
        fields[lbl] = _add_field(db, lbl, admin.id)
    created = updated = unchanged = 0
    for target, name, no, team_id, active, extra in plan:
        ex = {str(fields[k].id): v for k, v in extra.items()}
        if target is None:
            w = Worker(name=name, employee_no=no, team_id=team_id, is_active=True if active is None else active,
                       extra={k: v for k, v in ex.items() if v})
            db.add(w)
            db.flush()
            audit.log(db, user_id=admin.id, action="import", entity="worker", entity_id=w.id,
                      new={"name": name, "employee_no": no, "team_id": team_id})
            created += 1
            continue
        changes = {"name": name}
        if no:
            changes["employee_no"] = no
        if "team" in cols:
            changes["team_id"] = team_id
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
        b = _set_extra(db, target, new_extra, admin.id, action="import")
        if a or b:
            updated += 1
        else:
            unchanged += 1
    db.commit()
    return ImportResult(created=created, updated=updated, unchanged=unchanged, columns_added=added, errors=[])
