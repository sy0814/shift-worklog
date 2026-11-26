"""存储与备份：备份目录写进 txt 给 backup.ps1、目录检查、原图归档（搬到归档盘，盘不在时退回浏览图）。"""

import shutil
import tempfile
from datetime import timedelta
from pathlib import Path

from app import storage_service
from app.db import SessionLocal
from app.models import Attachment, utcnow

from .test_tasks import jpeg, new_task, upload


def test_backup_dirs_and_check(client, admin_h, leader_h):
    assert client.get("/api/storage", headers=leader_h).status_code == 403
    d = tempfile.mkdtemp()
    r = client.post("/api/storage/check", headers=admin_h, json={"path": d}).json()
    assert r["ok"] and r["free_gb"] > 0
    assert client.post("/api/storage/check", headers=admin_h, json={"path": "relative/dir"}).json()["ok"] is False
    up = str(storage_service.upload_root() / "x")
    assert client.post("/api/storage/check", headers=admin_h, json={"path": up}).json()["ok"] is False  # 不能放在图片目录里
    body = {"backup_dir": d + "/main", "backup_copy_dir": d + "/cloud", "archive_enabled": False, "archive_months": 6, "archive_dir": ""}
    r = client.put("/api/storage", headers=admin_h, json=body)
    assert r.status_code == 200, r.text
    assert (storage_service.data_dir() / "backup-target.txt").read_text(encoding="utf-8") == d + "/main"
    assert (storage_service.data_dir() / "backup-copy.txt").read_text(encoding="utf-8") == d + "/cloud"
    assert r.json()["archive_months"] == 6 and r.json()["status"] is None
    # backup.ps1 写的状态
    (storage_service.data_dir() / "backup-status.json").write_text('{"ok": true, "at": "2026-11-24 03:40", "size_mb": 12.5}', encoding="utf-8")
    assert client.get("/api/storage", headers=admin_h).json()["status"]["size_mb"] == 12.5
    # 清空 = 用默认目录
    client.put("/api/storage", headers=admin_h, json=body | {"backup_dir": "", "backup_copy_dir": ""})
    assert not (storage_service.data_dir() / "backup-target.txt").exists()
    assert client.put("/api/storage", headers=admin_h, json=body | {"archive_enabled": True}).status_code == 400  # 开归档必须填目录
    bad = client.put("/api/storage", headers=admin_h, json=body | {"backup_copy_dir": d + "/main/sub"})
    assert bad.status_code == 400 and "outside" in bad.json()["detail"]
    assert client.post("/api/storage/backup-now", headers=admin_h).status_code == 409  # 不是 Windows


def test_alert_lang(client, admin_h):
    """服务器报警语言：写进 watchdog-lang.txt 给 watchdog.ps1；中文是默认，不留文件；不传 = 不改；只认 zh / sr / en。"""
    f = storage_service.data_dir() / "watchdog-lang.txt"
    body = {"backup_dir": "", "backup_copy_dir": "", "archive_enabled": False, "archive_months": 12, "archive_dir": ""}
    assert client.get("/api/storage", headers=admin_h).json()["alert_lang"] == "zh"
    r = client.put("/api/storage", headers=admin_h, json=body | {"alert_lang": "sr"})
    assert r.status_code == 200 and r.json()["alert_lang"] == "sr"
    assert f.read_text(encoding="utf-8") == "sr"
    assert client.put("/api/storage", headers=admin_h, json=body).json()["alert_lang"] == "sr"  # 旧页面没传：不改
    assert client.put("/api/storage", headers=admin_h, json=body | {"alert_lang": "de"}).status_code == 422
    hist = client.get("/api/audit", headers=admin_h, params={"entity": "setting"}).json()
    items = hist["items"] if isinstance(hist, dict) else hist
    assert any(x.get("field") == "alert_lang" for x in items)
    client.put("/api/storage", headers=admin_h, json=body | {"alert_lang": "zh"})
    assert not f.exists()


def test_archive_originals(client, admin_h, leader_h):
    t = new_task(client, leader_h)
    a = upload(client, leader_h, t["id"], jpeg()).json()
    orig = client.get(a["url_original"])
    assert orig.status_code == 200 and "x-original-archived" not in orig.headers
    with SessionLocal() as db:  # 假装是 13 个月前传的
        row = db.get(Attachment, a["id"])
        row.uploaded_at = utcnow() - timedelta(days=400)
        src = storage_service.upload_root() / row.path_original
        rel = row.path_original
        db.commit()
    arch = tempfile.mkdtemp()
    client.put("/api/storage", headers=admin_h, json={"backup_dir": "", "backup_copy_dir": "", "archive_enabled": True,
                                                      "archive_months": 12, "archive_dir": arch})
    assert client.get("/api/storage", headers=admin_h).json()["due"] >= 1
    r = client.post("/api/storage/archive-now", headers=admin_h).json()
    assert r["moved"] >= 1 and not r["errors"]
    assert not src.exists() and (Path(arch) / rel).is_file()
    # 浏览图、缩略图还在原处；原图从归档盘读
    assert client.get(a["url_view"]).status_code == 200
    o2 = client.get(a["url_original"])
    assert o2.status_code == 200 and o2.content == orig.content
    # 归档盘拔掉了 → 退回浏览图
    shutil.move(arch, arch + "-gone")
    o3 = client.get(a["url_original"])
    assert o3.status_code == 200 and o3.headers.get("x-original-archived") == "1"
    shutil.move(arch + "-gone", arch)
    assert client.post("/api/storage/archive-now", headers=admin_h).json()["moved"] == 0  # 不会重复搬
