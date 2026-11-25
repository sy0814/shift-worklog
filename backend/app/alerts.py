"""报警：备份失败 / 太久没备份、磁盘快满。首页给管理员显示红色提醒（GET /api/alerts）。

服务停了这件事程序自己发现不了，由服务器上的看门狗（deploy/windows/watchdog.ps1，每 5 分钟）检查，
它也会检查备份和磁盘，在服务器上弹窗并写 Windows 事件日志。两边的阈值要一致（改了这里，也改 watchdog.ps1）。
"""

import os
import shutil
from datetime import datetime, timedelta
from pathlib import Path

from . import storage_service

DISK_MIN_GB = 5  # 剩余空间少于 5 GB
DISK_MIN_PCT = 10  # 或少于 10%
BACKUP_MAX_AGE_H = 26  # 每天 03:40 备份，超过 26 小时没有成功的备份就报警


def _disk(path: Path) -> dict | None:
    try:
        du = shutil.disk_usage(path)
    except OSError:
        return None
    free_gb = du.free / 1024**3
    pct = du.free * 100 / du.total if du.total else 100
    return {"path": str(path), "free_gb": round(free_gb, 1), "free_pct": round(pct, 1),
            "low": free_gb < DISK_MIN_GB or pct < DISK_MIN_PCT}


def current(now_local: datetime) -> list[dict]:
    """当前的问题列表：[{code, ...}]。code：backup_failed / backup_old / backup_never / disk_low。"""
    out: list[dict] = []
    st = storage_service.backup_status()
    target = storage_service.backup_dirs()["backup_dir"]
    if st is None:
        # 设了备份位置（Windows 安装脚本会设）但从没写过结果：备份从没跑过
        if target and os.name == "nt":
            out.append({"code": "backup_never"})
    elif not st.get("ok"):
        out.append({"code": "backup_failed", "at": st.get("at"), "message": st.get("message") or ""})
    else:
        try:
            at = datetime.strptime(str(st.get("at")), "%Y-%m-%d %H:%M")
        except ValueError:
            at = None
        if at is None or now_local - at > timedelta(hours=BACKUP_MAX_AGE_H):
            out.append({"code": "backup_old", "at": st.get("at"),
                        "hours": round((now_local - at).total_seconds() / 3600) if at else None})
    # 磁盘：图片目录、程序数据目录、备份目录（同一块盘只报一次）
    seen = set()
    for p in (storage_service.upload_root(), storage_service.data_dir(), Path(target) if target else None):
        if p is None or not p.exists():
            continue
        try:
            dev = os.stat(p).st_dev
        except OSError:
            continue
        if dev in seen:
            continue
        seen.add(dev)
        d = _disk(p)
        if d and d["low"]:
            out.append({"code": "disk_low", "path": d["path"], "free_gb": d["free_gb"], "free_pct": d["free_pct"]})
    return out
