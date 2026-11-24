"""设备台账：设备编号、名称、区域、型号、备注；任务可以关联设备。

- 看：所有登录的人（任务表单里选设备也要用）
- 新增 / 修改 / 停用 / 删除 / 导入：有 equipment.manage 权限的人（默认管理员、班长、副班长）
- 名称 / 区域 / 备注三语：只填一种也行，后台用 DeepSeek 补齐空着的语言；改了原文（录入语言）会重新翻译，
  只改某个译文 = 人工校对，保留
"""

import io
from datetime import datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import StreamingResponse
from openpyxl import Workbook, load_workbook
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .. import audit, permissions, translation_service
from ..db import get_db
from ..models import Equipment, Task, User, utcnow
from ..schemas import Lang, Trilingual, UTCDateTime
from ..security import get_current_user

router = APIRouter(prefix="/api/equipment", tags=["equipment"])
LANGS = ("zh", "sr", "en")
FIELDS = translation_service.EQUIPMENT_FIELDS
MAX = translation_service.EQUIPMENT_MAX
OPEN = ("not_started", "in_progress")


class EquipmentIn(BaseModel):
    code: str | None = Field(default=None, max_length=60)
    name: Trilingual | None = None
    area: Trilingual | None = None
    note: Trilingual | None = None
    model: str | None = Field(default=None, max_length=200)
    is_active: bool | None = None
    lang: Lang = "zh"  # 录入时的界面语言


class EquipmentOut(BaseModel):
    id: int
    code: str
    name: Trilingual
    area: Trilingual
    note: Trilingual
    model: str
    source_lang: str
    translation_status: str
    is_active: bool
    tasks_total: int = 0
    tasks_open: int = 0
    last_task_date: str | None = None
    updated_at: UTCDateTime
    can_manage: bool = False


def _tri(e: Equipment, f: str) -> Trilingual:
    return Trilingual(**{l: getattr(e, f"{f}_{l}") for l in LANGS})


def _out(e: Equipment, stats: dict, can: bool) -> EquipmentOut:
    total, open_, last = stats.get(e.id, (0, 0, None))
    return EquipmentOut(id=e.id, code=e.code, name=_tri(e, "name"), area=_tri(e, "area"), note=_tri(e, "note"),
                        model=e.model or "", source_lang=e.source_lang, translation_status=e.translation_status,
                        is_active=e.is_active, tasks_total=total, tasks_open=open_,
                        last_task_date=str(last) if last else None, updated_at=e.updated_at, can_manage=can)


def _stats(db: Session, ids: list[int] | None = None) -> dict:
    """设备 id → (任务数, 未完成数, 最近任务的班次日期)；已移交的不算（链上只算最新一条）。"""
    q = (select(Task.equipment_id, Task.status, func.count(), func.max(Task.shift_date))
         .where(Task.equipment_id.is_not(None), Task.status != "handed_over")
         .group_by(Task.equipment_id, Task.status))
    if ids is not None:
        q = q.where(Task.equipment_id.in_(ids))
    out: dict[int, list] = {}
    for eid, st, n, last in db.execute(q).all():
        cur = out.setdefault(eid, [0, 0, None])
        cur[0] += n
        if st in OPEN:
            cur[1] += n
        if last and (cur[2] is None or last > cur[2]):
            cur[2] = last
    return {k: tuple(v) for k, v in out.items()}


def _can(db: Session, user: User) -> bool:
    return permissions.who(db, user).has("equipment.manage")


def _require(db: Session, user: User) -> None:
    permissions.require(_can(db, user), "no permission to manage equipment")


def _clean_code(code: str | None) -> str:
    code = (code or "").strip()
    if not code:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "equipment code required")
    return code


def _apply(e: Equipment, body: EquipmentIn, creating: bool) -> tuple[dict, bool]:
    """算出要改的列。返回 (changes, 需要翻译)。
    改了原文（录入语言那一列）→ 其他语言清空重新翻译（除非同时也改了它们）；只改译文 = 人工校对，保留。"""
    changes: dict = {}
    need = False
    for f in FIELDS:
        tri: Trilingual | None = getattr(body, f)
        if tri is None:
            continue
        new = {l: (translation_service.fit(getattr(tri, l) or "", MAX[f]) or None) for l in LANGS}
        old = {l: (None if creating else getattr(e, f"{f}_{l}")) for l in LANGS}
        changed = [l for l in LANGS if new[l] != old[l]]
        if not changed:
            continue
        src = e.source_lang if not creating else None
        if not creating and src in changed and len(changed) == 1 and new[src]:
            for l in LANGS:  # 原文改了 → 旧译文作废
                if l != src:
                    new[l] = None
        for l in LANGS:
            if new[l] != old[l]:
                changes[f"{f}_{l}"] = new[l]
        if any(new.values()) and not all(new.values()):
            need = True
    return changes, need


@router.get("", response_model=list[EquipmentOut])
def list_equipment(q: str | None = Query(default=None, max_length=100), include_inactive: bool = False,
                   db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    query = select(Equipment)
    if not include_inactive:
        query = query.where(Equipment.is_active.is_(True))
    if q and q.strip():
        like = f"%{q.strip()}%"
        query = query.where(or_(Equipment.code.ilike(like), Equipment.model.ilike(like),
                                *[getattr(Equipment, f"{f}_{l}").ilike(like) for f in ("name", "area") for l in LANGS]))
    rows = db.scalars(query.order_by(Equipment.code)).all()
    stats = _stats(db)
    can = _can(db, user)
    return [_out(e, stats, can) for e in rows]


@router.get("/{eid}", response_model=EquipmentOut)
def get_equipment(eid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    e = db.get(Equipment, eid)
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return _out(e, _stats(db, [eid]), _can(db, user))


@router.post("", response_model=EquipmentOut, status_code=201)
def create_equipment(body: EquipmentIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require(db, user)
    code = _clean_code(body.code)
    if db.scalar(select(Equipment.id).where(Equipment.code == code)):
        raise HTTPException(status.HTTP_409_CONFLICT, "equipment code already exists")
    if body.name is None or not any((getattr(body.name, l) or "").strip() for l in LANGS):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "equipment name required")
    e = _create(db, user, code, body)
    db.commit()
    translation_service.enqueue_equipment(e.id)
    db.refresh(e)
    return _out(e, {}, True)


def _create(db: Session, user: User, code: str, body: EquipmentIn) -> Equipment:
    now = utcnow()
    name = body.name or Trilingual()
    src = body.lang if (getattr(name, body.lang) or "").strip() else next(
        (l for l in LANGS if (getattr(name, l) or "").strip()), body.lang)
    e = Equipment(code=code, model=(body.model or "").strip(), source_lang=src, translation_status="pending",
                  is_active=True if body.is_active is None else body.is_active,
                  created_by=user.id, updated_by=user.id, created_at=now, updated_at=now)
    changes, need = _apply(e, body, creating=True)
    for k, v in changes.items():
        setattr(e, k, v)
    e.translation_status = "pending" if need else "done"
    db.add(e)
    db.flush()
    audit.log(db, user_id=user.id, action="create", entity="equipment", entity_id=e.id,
              new={"code": code, "model": e.model, **changes})
    return e


@router.patch("/{eid}", response_model=EquipmentOut)
def update_equipment(eid: int, body: EquipmentIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _require(db, user)
    e = db.get(Equipment, eid)
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    changes = _update(db, e, body)
    if audit.log_changes(db, e, changes, user_id=user.id, entity="equipment", entity_id=e.id):
        e.updated_by, e.updated_at = user.id, utcnow()
    if translation_service.equipment_missing(e):
        e.translation_status = "pending"
    if e.name_zh is None and e.name_sr is None and e.name_en is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "equipment name required")
    db.commit()
    if e.translation_status == "pending":
        translation_service.enqueue_equipment(e.id)
    db.refresh(e)
    return _out(e, _stats(db, [e.id]), True)


def _update(db: Session, e: Equipment, body: EquipmentIn) -> dict:
    changes, _need = _apply(e, body, creating=False)
    if body.code is not None:
        code = _clean_code(body.code)
        if code != e.code:
            if db.scalar(select(Equipment.id).where(Equipment.code == code, Equipment.id != e.id)):
                raise HTTPException(status.HTTP_409_CONFLICT, "equipment code already exists")
            changes["code"] = code
    if body.model is not None:
        changes["model"] = body.model.strip()
    if body.is_active is not None:
        changes["is_active"] = body.is_active
    return changes


@router.delete("/{eid}", status_code=204)
def delete_equipment(eid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """只能删没关联过任务的设备；关联过的请停用。"""
    _require(db, user)
    e = db.get(Equipment, eid)
    if e is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if db.scalar(select(func.count()).select_from(Task).where(Task.equipment_id == eid)):
        raise HTTPException(status.HTTP_409_CONFLICT, "equipment has tasks; deactivate it instead")
    audit.log(db, user_id=user.id, action="delete", entity="equipment", entity_id=e.id,
              old={"code": e.code, "name": e.name_zh or e.name_sr or e.name_en})
    db.delete(e)
    db.commit()


# ---------------- Excel 导入 / 导出 ----------------
HEAD = {  # 列 → 三语表头
    "code": ("设备编号", "Šifra opreme", "Equipment code"),
    "name": ("名称", "Naziv", "Name"),
    "area": ("区域", "Lokacija", "Area"),
    "model": ("型号规格", "Model / tip", "Model"),
    "note": ("备注", "Napomena", "Note"),
    "active": ("在用", "Aktivna", "Active"),
}
ALIASES = {"编号": "code", "设备号": "code", "šifra": "code", "code": "code", "型号": "model", "规格": "model",
           "model": "model", "tip": "model", "位置": "area", "area": "area", "oblast": "area", "名字": "name",
           "设备名称": "name", "name": "name", "napomena": "note", "note": "note", "启用": "active", "active": "active"}
YES = {"1", "是", "在用", "y", "yes", "da", "true", "√", "✓"}
NO = {"0", "否", "停用", "n", "no", "ne", "false", "×"}


def _header_key(h: str) -> tuple[str, str | None] | None:
    """表头 → (列, 语言)。「名称 zh」「Naziv sr」= 指定语言；不带语言 = 导入时选的语言。"""
    h = (h or "").strip()
    if not h:
        return None
    lang = None
    parts = h.rsplit(None, 1)
    if len(parts) == 2 and parts[1].lower() in LANGS:
        h, lang = parts[0], parts[1].lower()
    for key, names in HEAD.items():
        if h.lower() in (n.lower() for n in names):
            return key, lang
    key = ALIASES.get(h.lower())
    return (key, lang) if key else None


@router.get("/export/xlsx")
def export_equipment(lang: Lang = "zh", db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    i = LANGS.index(lang)
    wb = Workbook()
    ws = wb.active
    ws.title = {"zh": "设备台账", "sr": "Oprema", "en": "Equipment"}[lang]
    cols = [("code", None)] + [(f, l) for f in ("name", "area") for l in LANGS] + [("model", None)] + \
        [("note", l) for l in LANGS] + [("active", None)]
    ws.append([HEAD[k][i] + (f" {l}" if l else "") for k, l in cols])
    for e in db.scalars(select(Equipment).order_by(Equipment.code)).all():
        row = []
        for k, l in cols:
            if k == "code":
                row.append(e.code)
            elif k == "model":
                row.append(e.model or "")
            elif k == "active":
                row.append(("是", "da", "yes")[i] if e.is_active else ("否", "ne", "no")[i])
            else:
                row.append(getattr(e, f"{k}_{l}") or "")
        ws.append(row)
    for col, w in zip("ABCDEFGHIJKLM", (14, 22, 22, 22, 16, 16, 16, 18, 24, 24, 24, 8)):
        ws.column_dimensions[col].width = w
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    audit.log(db, user_id=user.id, action="export", entity="equipment", entity_id="all")
    db.commit()
    fname = f"equipment-{datetime.now():%Y%m%d}.xlsx"
    return StreamingResponse(buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                             headers={"Content-Disposition": f'attachment; filename="{fname}"'})


class ImportRowError(BaseModel):
    row: int
    error: str


class ImportResult(BaseModel):
    created: int
    updated: int
    unchanged: int
    errors: list[ImportRowError]
    applied: bool


@router.post("/import/xlsx", response_model=ImportResult)
async def import_equipment(file: UploadFile = File(...), lang: Lang = Form("zh"), dry_run: bool = Form(True),
                           db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """按设备编号合并：编号已有 → 更新填了的格子；没有 → 新增。有一行错就全不导入。dry_run = 只检查。"""
    _require(db, user)
    data = await file.read()
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty file")
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "file too large")
    try:
        ws = load_workbook(io.BytesIO(data), read_only=True, data_only=True).active
    except Exception as err:  # noqa: BLE001
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "not an .xlsx file") from err
    rows = list(ws.iter_rows(values_only=True))
    if not rows:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "empty file")
    cols = [_header_key(str(h) if h is not None else "") for h in rows[0]]
    if not any(c and c[0] == "code" for c in cols):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "missing column: equipment code")
    existing = {e.code: e for e in db.scalars(select(Equipment)).all()}
    errors: list[ImportRowError] = []
    plan: list[tuple[str, Equipment | None, EquipmentIn]] = []
    seen: set[str] = set()
    for n, row in enumerate(rows[1:], start=2):
        vals: dict = {"name": {}, "area": {}, "note": {}}
        code = model = active = None
        for c, v in zip(cols, row):
            if c is None or v is None or str(v).strip() == "":
                continue
            v = str(v).strip()
            key, l = c
            if key == "code":
                code = v
            elif key == "model":
                model = v
            elif key == "active":
                if v.lower() in YES:
                    active = True
                elif v.lower() in NO:
                    active = False
                else:
                    errors.append(ImportRowError(row=n, error=f"bad active value: {v}"))
            else:
                vals[key][l or lang] = v
        if code is None and not any(vals[f] for f in vals) and model is None:
            continue  # 空行
        if not code:
            errors.append(ImportRowError(row=n, error="equipment code required"))
            continue
        if len(code) > 60:
            errors.append(ImportRowError(row=n, error="equipment code too long"))
            continue
        if code in seen:
            errors.append(ImportRowError(row=n, error=f"duplicate code in file: {code}"))
            continue
        seen.add(code)
        e = existing.get(code)
        if e is None and not vals["name"]:
            errors.append(ImportRowError(row=n, error="equipment name required"))
            continue
        body = EquipmentIn(code=code, model=model, is_active=active, lang=lang)
        for f in FIELDS:
            if vals[f]:  # 只更新填了的语言，没填的保持原样
                cur = {l: (getattr(e, f"{f}_{l}") if e else None) for l in LANGS}
                setattr(body, f, Trilingual(**(cur | vals[f])))
        plan.append((code, e, body))
    created = updated = unchanged = 0
    if errors:
        return ImportResult(created=0, updated=0, unchanged=0, errors=errors, applied=False)
    touched: list[Equipment] = []
    for code, e, body in plan:
        if e is None:
            created += 1
            if not dry_run:
                touched.append(_create(db, user, code, body))
            continue
        changes = _update(db, e, body)
        changes = {k: v for k, v in changes.items() if getattr(e, k) != v}
        if not changes:
            unchanged += 1
            continue
        updated += 1
        if not dry_run:
            audit.log_changes(db, e, changes, user_id=user.id, entity="equipment", entity_id=e.id)
            e.updated_by, e.updated_at = user.id, utcnow()
            if translation_service.equipment_missing(e):
                e.translation_status = "pending"
            touched.append(e)
    if dry_run:
        db.rollback()
        return ImportResult(created=created, updated=updated, unchanged=unchanged, errors=[], applied=False)
    audit.log(db, user_id=user.id, action="import", entity="equipment", entity_id="xlsx",
              new={"created": created, "updated": updated, "file": file.filename})
    db.commit()
    for e in touched:
        if e.translation_status == "pending":
            translation_service.enqueue_equipment(e.id)
    return ImportResult(created=created, updated=updated, unchanged=unchanged, errors=[], applied=True)
