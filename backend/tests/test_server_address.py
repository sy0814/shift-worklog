"""「系统设置 → 访问地址」：格式检查和 set-address.ps1 一致；不是 Windows 时不能在网页上改（测试环境是 Linux）。"""

import pytest

from app import server_address as sa
from app import storage_service


def test_normalize():
    assert sa.normalize(" 192.168.1.60 ，worklog-server ") == "192.168.1.60, worklog-server"
    assert sa.normalize("10.0.0.5, 10.0.0.5") == "10.0.0.5"
    for bad in ("", "  ", "192.168.1.300", "http://192.168.1.60", "192.168.1.60:443", "我的服务器", "-x", "a,b,c,d,e,f"):
        with pytest.raises(ValueError):
            sa.normalize(bad)


def test_get_and_put(client, admin_h, leader_h):
    assert client.get("/api/server-address", headers=leader_h).status_code == 403
    (storage_service.data_dir() / "site-hosts.txt").write_text("192.168.22.130", encoding="utf-8")
    g = client.get("/api/server-address", headers=admin_h).json()
    assert g["hosts"] == "192.168.22.130" and g["windows"] is False and isinstance(g["candidates"], list)
    r = client.put("/api/server-address", headers=admin_h, json={"hosts": "192.168.1.300"})
    assert r.status_code == 400 and "bad address" in r.json()["detail"]
    r = client.put("/api/server-address", headers=admin_h, json={"hosts": "192.168.1.60"})
    assert r.status_code == 409 and "only on the Windows server" in r.json()["detail"]
    assert not (storage_service.data_dir() / "site-hosts-request.txt").exists()


def test_request_on_windows_starts_task(client, admin_h, monkeypatch):
    """在 Windows 上：新地址写进 site-hosts-request.txt，启动计划任务 WorkRecordSetAddress，留痕；任务不存在 → 409 并删掉请求。"""
    from types import SimpleNamespace

    calls = []
    monkeypatch.setattr(sa, "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(sa.subprocess, "run", lambda args, **kw: calls.append(args) or SimpleNamespace(returncode=0))
    r = client.put("/api/server-address", headers=admin_h, json={"hosts": "192.168.1.60，worklog"})
    assert r.status_code == 200, r.text
    assert r.json()["pending"] == "192.168.1.60, worklog"
    assert calls == [["schtasks", "/Run", "/TN", "WorkRecordSetAddress"]]
    hist = client.get("/api/audit", headers=admin_h, params={"entity": "setting"}).json()
    items = hist["items"] if isinstance(hist, dict) else hist
    assert any(x.get("field") == "site_hosts" and x.get("new_value") == "192.168.1.60, worklog" for x in items)
    # 计划任务还没装（旧版本没有）
    monkeypatch.setattr(sa.subprocess, "run", lambda args, **kw: SimpleNamespace(returncode=1))
    r = client.put("/api/server-address", headers=admin_h, json={"hosts": "192.168.1.61"})
    assert r.status_code == 409 and "address task not found" in r.json()["detail"]
    assert not (storage_service.data_dir() / "site-hosts-request.txt").exists()
    # 计划任务跑完写的结果
    (storage_service.data_dir() / "site-hosts-status.json").write_text(
        '{"ok": false, "at": "2026-11-27 10:00:00", "hosts": "x", "message": "HTTPS 服务没有正常启动"}', encoding="utf-8")
    assert client.get("/api/server-address", headers=admin_h).json()["status"]["ok"] is False
