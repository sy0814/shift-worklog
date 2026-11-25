"""报警：备份失败 / 太久没备份、磁盘快满（管理员首页提醒）。"""

import json
from datetime import datetime

from app import alerts, storage_service


def _status(tmp_path, **kw):
    (tmp_path / "backup-status.json").write_text(json.dumps({"ok": True, "at": "2026-11-25 03:40"} | kw), encoding="utf-8")


def test_alerts(client, admin_h, leader_h, tmp_path, monkeypatch):
    monkeypatch.setattr(storage_service, "data_dir", lambda: tmp_path)
    now = datetime(2026, 11, 25, 10, 0)
    assert alerts.current(now) == []  # 没有备份状态文件（开发环境）：不报
    _status(tmp_path)
    assert alerts.current(now) == []
    assert [a["code"] for a in alerts.current(datetime(2026, 11, 26, 6, 0))] == ["backup_old"]  # 26 小时以上
    _status(tmp_path, ok=False, message="pg_dump 失败")
    a = alerts.current(now)
    assert a[0]["code"] == "backup_failed" and a[0]["message"] == "pg_dump 失败"
    # 磁盘快满（把阈值调到比实际剩余空间还大）
    _status(tmp_path)
    monkeypatch.setattr(alerts, "DISK_MIN_GB", 10**9)
    d = [x for x in alerts.current(now) if x["code"] == "disk_low"]
    assert d and d[0]["free_gb"] >= 0
    # 接口：只有管理员能看
    assert client.get("/api/alerts", headers=leader_h).status_code == 403
    r = client.get("/api/alerts", headers=admin_h)
    assert r.status_code == 200 and any(x["code"] == "disk_low" for x in r.json())
