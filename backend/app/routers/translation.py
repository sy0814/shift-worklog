"""人工校对译文、手动重新翻译、翻译状态、术语表维护。"""

import csv
import io

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from fastapi.responses import Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .. import audit, llm_config, translation_service, translator
from ..config import get_settings
from ..db import get_db
from ..models import GlossaryTerm, Task, User, utcnow
from ..schemas import (
    GlossaryIn,
    GlossaryOut,
    ImportResult,
    ManualTranslation,
    TaskOut,
    TranslationStatus,
)
from ..security import get_current_user, require_admin
from .tasks import _get_task, editable_team_ids, one_out

router = APIRouter(prefix="/api", tags=["translation"])


def _can_correct(db: Session, task: Task, user: User) -> bool:
    # 已移交 / 已废弃的任务也允许校对译文（只改译文，不改原文）；搭班的班组也可以
    editable = editable_team_ids(db, user)
    return editable is None or task.team_id in editable


@router.put("/tasks/{task_id}/translation", response_model=TaskOut)
def correct_translation(task_id: int, body: ManualTranslation, db: Session = Depends(get_db),
                        user: User = Depends(get_current_user)):
    """人工修正某段文字的某种语言译文，标记为人工校对，之后机器翻译不会覆盖它。"""
    task = _get_task(db, task_id)
    if not _can_correct(db, task, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your team's task")
    src_lang, src_text = translation_service.source_text(task, body.field)
    if not src_text:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "nothing to translate")
    if body.lang == src_lang:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "edit the original text via PATCH /tasks/{id}")
    text = body.text.strip()
    if body.lang == "sr":
        text = translator.to_latin(text)
    col = f"{body.field}_{body.lang}"
    audit.log_changes(db, task, {col: text}, user_id=user.id, entity="task", entity_id=task.id,
                      action="translate_manual")
    if col not in (task.manual_fields or []):
        task.manual_fields = [*(task.manual_fields or []), col]
    translation_service.refresh_status(task)
    task.updated_by = user.id
    task.updated_at = utcnow()
    db.commit()
    return one_out(db, _get_task(db, task.id), user)


@router.post("/tasks/{task_id}/retranslate", response_model=TaskOut)
def retranslate(task_id: int, keep_manual: bool = True, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    """立即重新翻译这条任务（同步执行，最多十几秒）。keep_manual=False 时连人工校对的也重翻。"""
    task = _get_task(db, task_id)
    if not _can_correct(db, task, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your team's task")
    if not translator.is_configured():
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "translation not configured")
    for field in translation_service.FIELDS:
        lang, text = translation_service.source_text(task, field)
        if not text:
            continue
        manual = set(task.manual_fields or [])
        for l in translator.LANGS:
            col = f"{field}_{l}"
            if l != lang and (not keep_manual or col not in manual):
                setattr(task, col, None)
        if not keep_manual:
            task.manual_fields = [m for m in (task.manual_fields or []) if not m.startswith(field + "_")]
    task.translation_attempts = 0
    task.translation_status = "pending"
    translation_service.refresh_status(task)
    audit.log(db, user_id=user.id, action="retranslate", entity="task", entity_id=task.id,
              extra={"keep_manual": keep_manual})
    db.commit()
    translation_service.translate_task(task.id)
    db.expire_all()
    return one_out(db, _get_task(db, task.id), user)


@router.get("/translation/status", response_model=TranslationStatus)
def translation_status(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    counts = dict(db.execute(select(Task.translation_status, func.count()).group_by(Task.translation_status)).all())
    return TranslationStatus(configured=translator.is_configured(), model=llm_config.current().translate_model,
                             counts=counts)


@router.post("/translation/retry-failed")
def retry_failed(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    n = translation_service.reset_failed(db)
    audit.log(db, user_id=admin.id, action="retry_failed", entity="system", entity_id="translation", new=n)
    db.commit()
    translation_service.retry_pending()
    return {"reset": n}


# ---------------- 术语表 ----------------
@router.get("/glossary", response_model=list[GlossaryOut])
def list_glossary(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    return db.scalars(select(GlossaryTerm).order_by(GlossaryTerm.category, GlossaryTerm.id)).all()


def _clean(body: GlossaryIn) -> dict:
    d = {k: v.strip() for k, v in body.model_dump().items()}
    d["sr"] = translator.to_latin(d["sr"])
    return d


@router.post("/glossary", response_model=GlossaryOut, status_code=201)
def add_term(body: GlossaryIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    d = _clean(body)
    if db.scalar(select(GlossaryTerm).where(GlossaryTerm.zh == d["zh"])):
        raise HTTPException(status.HTTP_409_CONFLICT, "term exists")
    t = GlossaryTerm(**d, updated_at=utcnow())
    db.add(t)
    db.flush()
    audit.log(db, user_id=admin.id, action="create", entity="glossary", entity_id=t.id, new=d)
    db.commit()
    return t


@router.put("/glossary/{term_id}", response_model=GlossaryOut)
def update_term(term_id: int, body: GlossaryIn, db: Session = Depends(get_db),
                admin: User = Depends(require_admin)):
    t = db.get(GlossaryTerm, term_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if audit.log_changes(db, t, _clean(body), user_id=admin.id, entity="glossary", entity_id=t.id):
        t.updated_at = utcnow()
    db.commit()
    return t


@router.delete("/glossary/{term_id}", status_code=204)
def delete_term(term_id: int, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    t = db.get(GlossaryTerm, term_id)
    if t is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    audit.log(db, user_id=admin.id, action="delete", entity="glossary", entity_id=t.id,
              old={"zh": t.zh, "sr": t.sr, "en": t.en, "category": t.category, "note": t.note})
    db.delete(t)
    db.commit()


def import_rows(db: Session, rows: list[dict], user_id: int | None) -> ImportResult:
    """按中文词条合并：已有的更新，没有的新增。"""
    added = updated = skipped = 0
    existing = {t.zh: t for t in db.scalars(select(GlossaryTerm))}
    for row in rows:
        row = {k.strip().lower(): (v or "").strip() for k, v in row.items() if k}
        zh, sr, en = row.get("zh", ""), row.get("sr", ""), row.get("en", "")
        if not (zh and sr and en):
            skipped += 1
            continue
        d = {"zh": zh[:200], "sr": translator.to_latin(sr)[:200], "en": en[:200],
             "category": row.get("category", "")[:50], "note": row.get("note", "")[:200]}
        t = existing.get(zh)
        if t is None:
            t = GlossaryTerm(**d, updated_at=utcnow())
            db.add(t)
            db.flush()
            existing[zh] = t
            audit.log(db, user_id=user_id, action="create", entity="glossary", entity_id=t.id, new=d)
            added += 1
        elif audit.log_changes(db, t, d, user_id=user_id, entity="glossary", entity_id=t.id):
            t.updated_at = utcnow()
            updated += 1
    return ImportResult(added=added, updated=updated, skipped=skipped)


@router.post("/glossary/import", response_model=ImportResult)
async def import_glossary(file: UploadFile = File(...), db: Session = Depends(get_db),
                          admin: User = Depends(require_admin)):
    data = await file.read(2 * 1024 * 1024)
    text = data.decode("utf-8-sig", errors="replace")  # Excel 另存的 CSV 带 BOM
    result = import_rows(db, list(csv.DictReader(io.StringIO(text))), admin.id)
    db.commit()
    return result


@router.get("/glossary/export")
def export_glossary(db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["zh", "sr", "en", "category", "note"])
    for t in db.scalars(select(GlossaryTerm).order_by(GlossaryTerm.category, GlossaryTerm.id)):
        w.writerow([t.zh, t.sr, t.en, t.category, t.note])
    return Response("﻿" + buf.getvalue(), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="glossary.csv"'})
