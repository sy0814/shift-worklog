"""「系统设置 → 存储与备份」（仅管理员）：备份位置、第二份备份、最近一次备份结果、立即备份；原图归档；服务器报警语言。"""

from pathlib import Path
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from .. import audit, storage_service
from ..db import get_db
from ..models import User
from ..security import require_admin

router = APIRouter(prefix="/api/storage", tags=["storage"])


class StorageIn(BaseModel):
    backup_dir: str = Field(default="", max_length=300)
    backup_copy_dir: str = Field(default="", max_length=300)
    archive_enabled: bool = False
    archive_months: int = Field(default=12, ge=1, le=120)
    archive_dir: str = Field(default="", max_length=300)
    alert_lang: Literal["zh", "sr", "en"] | None = None  # 服务器看门狗报警语言；不传 = 不改


class StorageOut(StorageIn):
    alert_lang: str
    default_backup_dir: str  # 没设置时用的目录
    status: dict | None  # 最近一次备份（backup.ps1 写的）
    archived: int  # 已归档的原图张数
    due: int  # 现在可以归档的张数
    windows: bool  # 服务器是不是 Windows（「立即备份」只在 Windows 上能用）


def _out(db: Session) -> StorageOut:
    import os

    return StorageOut(**storage_service.backup_dirs(), **storage_service.get_cfg(db), alert_lang=storage_service.alert_lang(),
                      default_backup_dir=str(storage_service.data_dir().parent / "backups"),
                      status=storage_service.backup_status(), **storage_service.archive_stats(db),
                      windows=os.name == "nt")


@router.get("", response_model=StorageOut)
def get_storage(db: Session = Depends(get_db), _: User = Depends(require_admin)):
    return _out(db)


class PathIn(BaseModel):
    path: str = Field(max_length=300)


@router.post("/check")
def check_path(body: PathIn, _: User = Depends(require_admin)):
    return storage_service.check_dir(body.path)


@router.put("", response_model=StorageOut)
def put_storage(body: StorageIn, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    for name in ("backup_dir", "backup_copy_dir", "archive_dir"):
        v = getattr(body, name).strip()
        if v:
            chk = storage_service.check_dir(v)
            if not chk["ok"]:
                raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{name}: {chk['error']}")
    if body.archive_enabled and not body.archive_dir.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "archive_dir: empty path")
    main = Path(body.backup_dir.strip() or str(storage_service.data_dir().parent / "backups"))
    if body.backup_copy_dir.strip():
        cp = Path(body.backup_copy_dir.strip())
        if cp == main or main in cp.parents or cp in main.parents:  # 互相包含会无限复制
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "backup_copy_dir: must be outside backup_dir")
    old = storage_service.backup_dirs() | storage_service.get_cfg(db) | {"alert_lang": storage_service.alert_lang()}
    storage_service.set_backup_dirs(body.backup_dir, body.backup_copy_dir)
    storage_service.set_cfg(db, body.model_dump())
    if body.alert_lang:
        storage_service.set_alert_lang(body.alert_lang)
    new = storage_service.backup_dirs() | storage_service.get_cfg(db) | {"alert_lang": storage_service.alert_lang()}
    for k in new:
        if old.get(k) != new[k]:
            audit.log(db, user_id=admin.id, action="update", entity="setting", entity_id=storage_service.KEY,
                      field=k, old=old.get(k), new=new[k])
    db.commit()
    return _out(db)


@router.post("/backup-now", status_code=202)
def backup_now(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    try:
        storage_service.run_backup_now()
    except (RuntimeError, OSError) as e:
        raise HTTPException(status.HTTP_409_CONFLICT, f"backup: {e}") from e
    audit.log(db, user_id=admin.id, action="backup", entity="setting", entity_id=storage_service.KEY)
    db.commit()


@router.post("/archive-now")
def archive_now(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    r = storage_service.archive_originals(db)
    return r | storage_service.archive_stats(db)
