"""设备统计：按移交链计数（移交两次的一件事只算一次）、任务类型、反复故障、时间线、导出。"""

import io
import uuid
from datetime import date, timedelta

import pytest
from openpyxl import load_workbook

from .conftest import login


@pytest.fixture(scope="module")
def teams(client, admin_h):
    return {t["code"]: t["id"] for t in client.get("/api/teams", headers=admin_h).json()}


def eq(client, h, code, name):
    r = client.post("/api/equipment", headers=h, json={"code": code, "name": {"zh": name}, "area": {"zh": "磨矿车间"}})
    assert r.status_code == 201, r.text
    return r.json()["id"]


def task(client, h, equipment_id, kind, text="设备问题", **kw):
    r = client.post("/api/tasks", headers=h, json={"client_id": str(uuid.uuid4()), "content": text, "lang": "zh",
                                                   "equipment_id": equipment_id, "kind": kind} | kw)
    assert r.status_code == 201, r.text
    return r.json()


def test_kind_saved_edited_and_handed_over(client, leader_h, teams):
    e = eq(client, leader_h, "KIND-1", "类型测试")
    t = task(client, leader_h, e, "maintenance")
    assert t["kind"] == "maintenance"
    t = client.patch(f"/api/tasks/{t['id']}", headers=leader_h, json={"kind": "fault"}).json()
    assert t["kind"] == "fault"
    new = client.post("/api/handover", headers=leader_h, json={"task_ids": [t["id"]], "to_team_id": teams["T2"]}).json()[0]
    assert new["kind"] == "fault"  # 移交时带过去
    assert task(client, leader_h, None, "other")["kind"] == "other"
    assert client.post("/api/tasks", headers=leader_h, json={"client_id": str(uuid.uuid4()), "content": "x", "lang": "zh",
                                                              "kind": "nonsense"}).status_code == 422


def test_stats(client, admin_h, leader_h, teams):
    mill = eq(client, admin_h, "STAT-MILL", "3号球磨机")
    pump = eq(client, admin_h, "STAT-PUMP", "渣浆泵")
    # 第 1 件故障：1 班开始、写日志、移交给 2 班，2 班写日志并完成 → 只算 1 次，移交 1 次，日志 2 条
    a = task(client, leader_h, mill, "fault", "主轴承温度高", status="in_progress")
    client.post(f"/api/tasks/{a['id']}/logs", headers=leader_h, json={"content": "拆开检查，缺密封圈", "lang": "zh"})
    b = client.post("/api/handover", headers=leader_h, json={"task_ids": [a["id"]], "to_team_id": teams["T2"]}).json()[0]
    t2 = login(client, "t2_leader1", "t2_leader1")
    client.post(f"/api/tasks/{b['id']}/logs", headers=t2, json={"content": "密封圈已换好", "lang": "zh"})
    assert client.post(f"/api/tasks/{b['id']}/status", headers=t2, json={"status": "done"}).status_code == 200
    # 再 2 件故障（未完成）→ 30 天内 3 次故障 = 反复；1 件检修（已完成）；泵 1 件巡查
    task(client, leader_h, mill, "fault", "又发热")
    task(client, leader_h, mill, "fault", "异响")
    task(client, leader_h, mill, "maintenance", "换润滑油", status="done")
    task(client, leader_h, pump, "inspection", "日常巡查", status="done")

    # 任务记在录入班组「这个班或下一个班」，不在班时可能是几天后：查询范围放宽
    rng = {"start": str(date.today() - timedelta(days=30)), "end": str(date.today() + timedelta(days=10))}
    r = client.get("/api/equipment-stats", headers=leader_h, params=rng)
    assert r.status_code == 200, r.text
    s = r.json()
    rows = {x["equipment"]["code"]: x for x in s["items"]}
    m = rows["STAT-MILL"]
    assert (m["fault"], m["maintenance"], m["inspection"], m["total"]) == (3, 1, 0, 4)
    assert m["open"] == 2 and m["handovers"] == 1 and m["logs"] == 2
    assert m["repeat"] is True and m["repeat_max"] == 3
    assert m["avg_hours"] is not None and m["avg_hours"] >= 0
    p = rows["STAT-PUMP"]
    assert (p["fault"], p["inspection"], p["repeat"]) == (0, 1, False)
    # 故障多的排前面
    codes = [x["equipment"]["code"] for x in s["items"]]
    assert codes.index("STAT-MILL") < codes.index("STAT-PUMP")

    # 时间线：新的在前；第 1 件事带着链上两班的日志、经过两个班组
    tl = client.get(f"/api/equipment-stats/{mill}/timeline", headers=leader_h).json()
    assert len(tl) == 4
    first = next(x for x in tl if x["task_id"] == a["id"])
    assert first["last_task_id"] == b["id"] and first["status"] == "done" and first["hours"] is not None
    assert [x["content"]["zh"] for x in first["logs"]] == ["拆开检查，缺密封圈", "密封圈已换好"]
    assert first["team_ids"] == [teams["T1"], teams["T2"]]

    # 导出
    x = client.get("/api/equipment-stats/xlsx", headers=admin_h, params={"lang": "en"})
    assert x.status_code == 200
    ws = load_workbook(io.BytesIO(x.content)).active
    head = [c.value for c in ws[2]]
    row = next(r for r in ws.iter_rows(min_row=3, values_only=True) if r[0] == "STAT-MILL")
    rec = dict(zip(head, row))
    assert rec["Breakdowns"] == 3 and rec["Recurring"] == "yes" and rec["Handovers"] == 1

    # 时间段不对
    assert client.get("/api/equipment-stats", headers=admin_h,
                      params={"start": "2026-01-01", "end": "2025-01-01"}).status_code == 400
