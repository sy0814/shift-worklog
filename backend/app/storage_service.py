"""存储与备份：
- 备份目录（主）、第二份备份目录（另一块盘 / 网络共享 / 云盘同步文件夹）：写进 data 目录下的
  backup-target.txt / backup-copy.txt，由 Windows 计划任务里的 backup.ps1 读取；backup.ps1 把结果写进
  backup-status.json，这里读出来给页面显示
- 原图归档：上传超过 N 个月的原图搬到归档目录（另一块盘），浏览图和缩略图留在原处，系统照常显示；
  归档盘没接上时，看「原图」会退回浏览图
"""

import json
import logging
import os
import re
import shutil
import subprocess
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import get_settings
from .models import AppSetting, Attachment

log = logging.getLogger(__name__)

KEY = "storage"
DEFAULTS = {"archive_enabled": False, "archive_months": 12, "archive_dir": ""}
BACKUP_TASK = "WorkRecordBackup"  # deploy/windows/common.ps1 的 $TaskBackup


def upload_root() -> Path:
    return Path(get_settings().upload_dir).resolve()


def data_dir() -> Path:
    """C:\\WorkRecord\\data（uploads 的上一级）。"""
    return upload_root().parent


def get_cfg(db: Session) -> dict:
    row = db.get(AppSetting, KEY)
    out = dict(DEFAULTS)
    if row is not None and isinstance(row.value, dict):
        out |= {k: row.value[k] for k in DEFAULTS if k in row.value}
    return out


def set_cfg(db: Session, cfg: dict) -> None:
    row = db.get(AppSetting, KEY)
    value = {k: cfg.get(k, DEFAULTS[k]) for k in DEFAULTS}
    if row is None:
        db.add(AppSetting(key=KEY, value=value))
    else:
        row.value = value


# ---------------- 目录 ----------------
_ABS = re.compile(r"^([A-Za-z]:[\\/]|\\\\[^\\]+\\[^\\]+)")  # D:\xxx 或 \\服务器\共享


def is_abs(path: str) -> bool:
    return bool(_ABS.match(path)) or (os.name != "nt" and path.startswith("/"))


def check_dir(path: str) -> dict:
    """能不能用作备份 / 归档目录：绝对路径、能创建、能写；返回剩余空间。"""
    path = (path or "").strip()
    if not path:
        return {"ok": False, "error": "empty path"}
    if not is_abs(path):
        return {"ok": False, "error": "path must be absolute"}
    p = Path(path)
    try:
        if p.resolve() == upload_root() or upload_root() in p.resolve().parents:
            return {"ok": False, "error": "path is inside the photo folder"}
        p.mkdir(parents=True, exist_ok=True)
        probe = p / f".write-test-{uuid.uuid4().hex[:8]}"
        probe.write_bytes(b"ok")
        probe.unlink()
        du = shutil.disk_usage(p)
        return {"ok": True, "free_gb": round(du.free / 1024**3, 1), "total_gb": round(du.total / 1024**3, 1)}
    except OSError as e:
        return {"ok": False, "error": f"cannot write: {e.strerror or e}"}


def _read_txt(name: str) -> str:
    f = data_dir() / name
    try:
        return f.read_text(encoding="utf-8-sig").strip()
    except OSError:
        return ""


def _write_txt(name: str, value: str) -> None:
    f = data_dir() / name
    if value:
        f.write_text(value, encoding="utf-8")  # 不带 BOM；backup.ps1 用 Get-Content 读
    elif f.exists():
        f.unlink()


def backup_dirs() -> dict:
    return {"backup_dir": _read_txt("backup-target.txt"), "backup_copy_dir": _read_txt("backup-copy.txt")}


def set_backup_dirs(backup_dir: str, copy_dir: str) -> None:
    _write_txt("backup-target.txt", backup_dir.strip())
    _write_txt("backup-copy.txt", copy_dir.strip())


def backup_status() -> dict | None:
    """backup.ps1 每次运行后写的 backup-status.json。"""
    f = data_dir() / "backup-status.json"
    try:
        return json.loads(f.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        return None


def run_backup_now() -> None:
    """立即运行 Windows 计划任务里的备份（只在 Windows 服务器上有用）。"""
    if os.name != "nt":
        raise RuntimeError("only on the Windows server")
    r = subprocess.run(["schtasks", "/Run", "/TN", BACKUP_TASK], capture_output=True, timeout=30)  # noqa: S603,S607
    if r.returncode != 0:
        raise RuntimeError("backup task not found; run install.ps1 again")


# ---------------- 原图归档 ----------------
def _aware(d: datetime) -> datetime:
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def archive_stats(db: Session) -> dict:
    cfg = get_cfg(db)
    cutoff = datetime.now(timezone.utc) - timedelta(days=30 * int(cfg["archive_months"]))
    archived = db.scalar(select(func.count(func.distinct(Attachment.path_original)))
                         .where(Attachment.archived_at.is_not(None))) or 0
    due = db.scalar(select(func.count(func.distinct(Attachment.path_original)))
                    .where(Attachment.archived_at.is_(None), Attachment.uploaded_at < cutoff)) or 0
    return {"archived": archived, "due": due}


def original_file(a: Attachment) -> Path | None:
    """原图现在在哪：没归档 → 图片目录；归档了 → 归档目录（盘没接上就返回 None）。"""
    if a.archived_at is None:
        return upload_root() / a.path_original
    from .db import SessionLocal

    with SessionLocal() as db:
        adir = get_cfg(db)["archive_dir"]
    if adir:
        p = Path(adir) / a.path_original
        if p.is_file():
            return p
    p = upload_root() / a.path_original  # 从备份恢复后原图又回到了图片目录
    return p if p.is_file() else None


def archive_originals(db: Session, now: datetime | None = None, limit: int = 2000) -> dict:
    """把上传超过 N 个月的原图搬到归档目录。同一个文件（移交后多条记录指向它）只搬一次。"""
    cfg = get_cfg(db)
    adir = (cfg["archive_dir"] or "").strip()
    if not adir:
        return {"moved": 0, "bytes": 0, "errors": ["archive folder not set"]}
    chk = check_dir(adir)
    if not chk["ok"]:
        return {"moved": 0, "bytes": 0, "errors": [f"archive folder: {chk['error']}"]}
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=30 * int(cfg["archive_months"]))
    paths = db.scalars(select(Attachment.path_original).where(Attachment.archived_at.is_(None))
                       .group_by(Attachment.path_original)
                       .having(func.max(Attachment.uploaded_at) < cutoff).limit(limit)).all()
    root, dest_root = upload_root(), Path(adir)
    moved = size = 0
    errors: list[str] = []
    for rel in paths:
        src, dst = root / rel, dest_root / rel
        try:
            if src.is_file():
                dst.parent.mkdir(parents=True, exist_ok=True)
                tmp = dst.with_name(dst.name + ".part")
                shutil.copy2(src, tmp)
                if tmp.stat().st_size != src.stat().st_size:
                    tmp.unlink()
                    raise OSError("size mismatch after copy")
                os.replace(tmp, dst)
                size += src.stat().st_size
                src.unlink()
            elif not dst.is_file():
                continue  # 两边都没有：不标记，留给管理员查
            for a in db.scalars(select(Attachment).where(Attachment.path_original == rel)):
                a.archived_at = now
            db.commit()
            moved += 1
        except OSError as e:
            db.rollback()
            errors.append(f"{rel}: {e}")
            if len(errors) >= 20:
                break
    if moved or errors:
        from . import audit

        audit.log(db, user_id=None, action="archive", entity="setting", entity_id=KEY,
                  new={"moved": moved, "bytes": size, "errors": errors[:5]})
        db.commit()
    return {"moved": moved, "bytes": size, "errors": errors}


def archive_job() -> None:
    """定时任务（每天凌晨）：开了归档就搬一次。"""
    from .db import SessionLocal

    with SessionLocal() as db:
        if not get_cfg(db)["archive_enabled"]:
            return
        r = archive_originals(db)
        if r["moved"] or r["errors"]:
            log.info("archive originals: %s", r)
