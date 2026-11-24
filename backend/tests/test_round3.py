"""第三轮：系统名称、班组整体调班、加班。"""

from datetime import date, datetime, timedelta

import pytest

from app.db import SessionLocal
from app.schedule_service import load_schedule, local_now
from app.shifts import Schedule, TeamInfo

from .conftest import login

LOGIN = {"T1": "t1_leader1", "T2": "t2_leader1", "T3": "t3_leader1", "T4": "t4_leader1", "DAY": "day_leader1"}


@pytest.fixture(scope="module")
def teams(client, admin_h):
    return {t["code"]: t["id"] for t in client.get("/api/teams", headers=admin_h).json()}


def h(client, code):
    return login(client, LOGIN[code], LOGIN[code])


def test_branding(client, admin_h, leader_h):
    assert client.get("/api/branding").json() == {"zh": "", "sr": "", "en": ""}  # 登录前也能读
    assert client.put("/api/branding", headers=leader_h, json={"zh": "x"}).status_code == 403
    r = client.put("/api/branding", headers=admin_h, json={"zh": " 选矿厂交接班 ", "en": "Plant log"})
    assert r.json() == {"zh": "选矿厂交接班", "sr": "", "en": "Plant log"}
    assert client.get("/api/branding").json()["en"] == "Plant log"
    client.put("/api/branding", headers=admin_h, json={})


def test_schedule_override_pure():
    s = Schedule(base_date=date(2026, 11, 1), teams=(TeamInfo(1, "rotating", 4), TeamInfo(3, "rotating", 0)),
                 overrides={(1, date(2026, 11, 21)): "off"})
    assert s.planned_shift_of(TeamInfo(1, "rotating", 4), date(2026, 11, 21)) == "day"
    assert s.shift_of(TeamInfo(1, "rotating", 4), date(2026, 11, 21)) == "off"
    assert s.rotating_team_on(date(2026, 11, 21), "day") is None


def test_team_shift_override(client, admin_h, leader_h, teams):
    d = date(2027, 3, 10)
    cal = client.get("/api/shifts/calendar", headers=admin_h, params={"start": d, "end": d}).json()[0]
    planned = cal["shifts"][str(teams["T2"])]
    target = "night" if planned != "night" else "day"
    body = {"team_id": teams["T2"], "start": str(d), "end": str(d + timedelta(days=1)), "shift_kind": target, "note": "检修"}
    assert client.put("/api/team-shifts", headers=leader_h, json=body).status_code == 403
    r = client.put("/api/team-shifts", headers=admin_h, json=body)
    assert r.status_code == 200 and len(r.json()) >= 1
    cal = client.get("/api/shifts/calendar", headers=admin_h, params={"start": d, "end": d}).json()[0]
    assert cal["shifts"][str(teams["T2"])] == target and cal["changed"][str(teams["T2"])] == planned
    # 出勤默认值也跟着变
    w = client.post("/api/workers", headers=admin_h, json={"name": "Override W", "team_id": teams["T2"]}).json()
    grid = client.get("/api/attendance", headers=admin_h, params={"start": d, "end": d, "team_id": teams["T2"]}).json()
    assert target in str(grid)
    # 恢复
    assert client.delete("/api/team-shifts", headers=admin_h, params={"team_id": teams["T2"], "start": str(d), "end": str(d + timedelta(days=1))}).status_code == 204
    cal = client.get("/api/shifts/calendar", headers=admin_h, params={"start": d, "end": d}).json()[0]
    assert cal["shifts"][str(teams["T2"])] == planned and cal["changed"] == {}
    # 设成和原排班一样 = 不记录
    r = client.put("/api/team-shifts", headers=admin_h, json=body | {"shift_kind": planned, "end": str(d)})
    assert r.json() == []
    assert w["id"]


def test_overtime(client, admin_h, leader_h, teams):
    with SessionLocal() as db:
        sched = load_schedule(db)
        d, k = sched.shift_at(local_now())
        main = sched.rotating_team_on(d, k)
    code = next(c for c, i in teams.items() if i == main.id)
    ws = client.post("/api/workers/bulk", headers=admin_h, json={"names": ["OT A", "OT B"], "team_id": main.id}).json()
    lh = h(client, code)
    end = {"day": "15:00", "middle": "23:00", "night": "07:00"}[k]
    until = {"day": "18:30", "middle": "01:00", "night": "09:00"}[k]
    # 个人加班
    r = client.post("/api/overtime", headers=lh, json={"day": str(d), "worker_ids": [ws[0]["id"]], "until": until})
    assert r.status_code == 201, r.text
    o = r.json()[0]
    assert o["shift_kind"] == k and o["hours"] in (3.5, 2.0) and o["worker_name"] == "OT A"
    # 别的班组的班长不能给这个班组设加班
    other = next(c for c in ("T1", "T2", "T3", "T4") if c != code)
    assert client.post("/api/overtime", headers=h(client, other), json={"day": str(d), "team_id": main.id, "until": until}).status_code == 403
    # 整个班组
    r = client.post("/api/overtime", headers=lh, json={"day": str(d), "team_id": main.id, "until": until, "note": "抢修"})
    assert r.status_code == 201 and r.json()[0]["people"] >= 2
    # 超过 16 小时不行；两个都给 / 都不给不行
    assert client.post("/api/overtime", headers=lh, json={"day": str(d), "team_id": main.id, "until": end}).status_code == 400  # = 24 小时后
    assert client.post("/api/overtime", headers=lh, json={"day": str(d), "until": until}).status_code == 400
    # 在岗人员显示加班到几点
    duty = client.get("/api/duty", headers=admin_h).json()
    me = [p for t in duty["teams"] for p in t["workers"] if p["worker"]["id"] == ws[0]["id"]][0]
    assert me["overtime_until"] and me["overtime_until"][11:16] == until
    # 导出里有加班时长
    lst = client.get("/api/overtime", headers=admin_h, params={"start": str(d), "end": str(d)}).json()
    assert {x["id"] for x in lst} >= {o["id"]}
    ppl = client.get("/api/overtime/people", headers=admin_h, params={"start": str(d), "end": str(d), "team_id": main.id}).json()
    assert {p["worker_id"] for p in ppl} >= {ws[0]["id"], ws[1]["id"]}
    # 删除（留痕）
    assert client.delete(f"/api/overtime/{o['id']}", headers=lh).status_code == 204
    assert o["id"] not in {x["id"] for x in client.get("/api/overtime", headers=admin_h, params={"start": str(d), "end": str(d)}).json()}


def test_overtime_hours_in_stats(client, admin_h, teams):
    from app.overtime_service import hours_by_worker
    from app.models import Worker
    with SessionLocal() as db:
        sched = load_schedule(db)
        d, k = sched.shift_at(local_now())
        main = sched.rotating_team_on(d, k)
        ws = list(db.query(Worker).filter(Worker.team_id == main.id))
        hrs = hours_by_worker(db, d, d, ws)
    names = {w.id: w.name for w in ws}
    assert any(names[i] == "OT B" and v > 0 for i, v in hrs.items())  # 全班加班算到 OT B 头上


def test_worker_roster_columns_and_excel(client, admin_h, leader_h, teams):
    import io

    from openpyxl import Workbook, load_workbook

    # 加列（班长不行）、改列名
    assert client.post("/api/workers/fields", headers=leader_h, json={"label": "电话"}).status_code == 403
    f = client.post("/api/workers/fields", headers=admin_h, json={"label": "电话"}).json()
    assert client.post("/api/workers/fields", headers=admin_h, json={"label": "电话"}).status_code == 409
    w = client.post("/api/workers", headers=admin_h, json={"name": "Roster Ana", "employee_no": "R001",
                                                           "team_id": teams["T1"], "extra": {str(f["id"]): "123"}}).json()
    assert w["extra"] == {str(f["id"]): "123"}
    # 逐格修改：只改给出的列，空 = 清空；未知列报错
    r = client.patch(f"/api/workers/{w['id']}", headers=admin_h, json={"extra": {str(f["id"]): "456"}}).json()
    assert r["extra"][str(f["id"])] == "456"
    assert client.patch(f"/api/workers/{w['id']}", headers=admin_h, json={"extra": {"9999": "x"}}).status_code == 400
    hist = client.get("/api/audit", headers=admin_h, params={"entity": "worker", "entity_id": str(w["id"])}).json()["items"]
    assert any(h["field"] == "[电话]" and h["old_value"] and "123" in h["old_value"] for h in hist)
    client.put(f"/api/workers/fields/{f['id']}", headers=admin_h, json={"label": "手机"})

    # 导出
    x = client.get("/api/workers/export.xlsx", headers=admin_h, params={"lang": "zh"})
    assert x.status_code == 200
    ws = load_workbook(io.BytesIO(x.content)).active
    head = [c.value for c in ws[1]]
    assert head[:4] == ["工号", "姓名", "班组", "在职"] and "手机" in head
    row = next(r for r in ws.iter_rows(values_only=True) if r[1] == "Roster Ana")
    assert row[0] == "R001" and row[head.index("手机")] == "456"

    # 导入：塞语表头；更新已有（按工号）、新建、新列自动加上
    wb = Workbook()
    s = wb.active
    s.append(["Matični br.", "Ime", "Ekipa", "Aktivan", "手机", "Kvalifikacija"])
    s.append(["R001", "Roster Ana", "2班", "da", "789", "Električar"])
    s.append([None, "Roster Novi", "T3", None, None, "Mehaničar"])
    buf = io.BytesIO()
    wb.save(buf)
    up = lambda b: client.post("/api/workers/import", headers=admin_h,
                               files={"file": ("w.xlsx", b, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    r = up(buf.getvalue()).json()
    assert r["errors"] == [] and r["created"] == 1 and r["updated"] == 1 and r["columns_added"] == ["Kvalifikacija"]
    lst = {x["name"]: x for x in client.get("/api/workers", headers=admin_h).json()}
    fields = {x["label"]: str(x["id"]) for x in client.get("/api/workers/fields", headers=admin_h).json()}
    assert lst["Roster Ana"]["team_id"] == teams["T2"] and lst["Roster Ana"]["extra"][fields["手机"]] == "789"
    assert lst["Roster Novi"]["team_id"] == teams["T3"] and lst["Roster Novi"]["extra"][fields["Kvalifikacija"]] == "Mehaničar"

    # 有一行错 → 整个文件都不导入
    wb = Workbook()
    s = wb.active
    s.append(["姓名", "班组"])
    s.append(["Roster Bad1", "1班"])
    s.append(["Roster Bad2", "9班"])
    buf = io.BytesIO()
    wb.save(buf)
    r = up(buf.getvalue()).json()
    assert r["created"] == 0 and len(r["errors"]) == 1 and r["errors"][0].startswith("3:")
    assert "Roster Bad1" not in {x["name"] for x in client.get("/api/workers", headers=admin_h).json()}

    # 删列：值一起删掉
    assert client.delete(f"/api/workers/fields/{fields['Kvalifikacija']}", headers=admin_h).status_code == 204
    lst = {x["name"]: x for x in client.get("/api/workers", headers=admin_h).json()}
    assert fields["Kvalifikacija"] not in lst["Roster Novi"]["extra"]
