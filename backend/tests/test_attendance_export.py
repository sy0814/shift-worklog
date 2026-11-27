import io
import uuid

import pytest
from openpyxl import Workbook, load_workbook

from .conftest import login


@pytest.fixture(scope="module")
def teams(client, admin_h):
    return {t["code"]: t["id"] for t in client.get("/api/teams", headers=admin_h).json()}


@pytest.fixture(scope="module")
def ws(client, admin_h, teams):
    """1 班两人（一人有工号）、常白班一人。"""
    a = client.post("/api/workers", headers=admin_h, json={"name": "Att Petar", "employee_no": "E100", "team_id": teams["T1"]}).json()
    b = client.post("/api/workers", headers=admin_h, json={"name": "Att 张伟", "team_id": teams["T1"]}).json()
    c = client.post("/api/workers", headers=admin_h, json={"name": "Att Day", "team_id": teams["DAY"]}).json()
    return {"a": a["id"], "b": b["id"], "c": c["id"]}


def grid(client, h, team_id, start, end):
    r = client.get("/api/attendance", headers=h, params={"team_id": team_id, "start": start, "end": end})
    assert r.status_code == 200, r.text
    return r.json()


def test_default_from_schedule(client, leader_h, teams, ws):
    # 1 班：11-21 白1，11-23 中1，11-25 休，11-26 夜1（11-25 23:00 开始），11-28 休
    g = grid(client, leader_h, teams["T1"], "2026-11-21", "2026-11-28")
    row = g["cells"][str(ws["a"])]
    assert [row[d]["shift_kind"] or row[d]["status"] for d in
            ["2026-11-21", "2026-11-23", "2026-11-25", "2026-11-26", "2026-11-28"]] == ["day", "middle", "off", "night", "off"]
    assert all(c["source"] == "default" for c in row.values())
    # 常白班：周六休息，周一上白班
    d = grid(client, leader_h, teams["DAY"], "2026-11-21", "2026-11-23")["cells"][str(ws["c"])]
    assert d["2026-11-21"]["status"] == "off" and d["2026-11-23"]["shift_kind"] == "day"


def test_manual_override_and_reset(client, admin_h, leader_h, teams, ws):
    put = lambda h, **kw: client.put("/api/attendance", headers=h, json={"worker_id": ws["a"], "day": "2026-11-21"} | kw)
    r = put(leader_h, status="leave", note="年假")
    assert r.status_code == 200 and r.json()["status"] == "leave" and r.json()["source"] == "manual"
    # 2 班班长不能改 1 班的人
    t2 = login(client, "t2_leader1", "t2_leader1")
    assert put(t2, status="present").status_code == 403
    # 休息日顶班
    r = client.put("/api/attendance", headers=leader_h, json={"worker_id": ws["a"], "day": "2026-11-27",
                                                              "status": "present", "shift_kind": "night", "team_id": teams["T4"]})
    assert r.json()["shift_kind"] == "night" and r.json()["team_id"] == teams["T4"]
    # 恢复默认
    assert put(leader_h, status="default").json()["source"] == "default"
    logs = client.get("/api/audit", headers=admin_h, params={"entity": "attendance", "entity_id": f"{ws['a']}:2026-11-21"}).json()["items"]
    assert [l["action"] for l in logs] == ["delete", "create"]
    assert put(leader_h, status="vacation").status_code == 400


def _xlsx(rows):
    wb = Workbook()
    sh = wb.active
    sh.append(["日期", "工号", "姓名", "状态", "班次", "备注"])
    for r in rows:
        sh.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _import(client, h, rows):
    return client.post("/api/attendance/import", headers=h,
                       files={"file": ("a.xlsx", _xlsx(rows), "application/octet-stream")})


def test_import_all_or_nothing(client, admin_h, leader_h, teams, ws):
    assert _import(client, leader_h, []).status_code == 403
    r = _import(client, admin_h, [
        ["2026-11-22", "E100", "", "病假", "", "flu"],
        ["22.11.2026", "", "Att 张伟", "xyz", "", ""],          # 状态错
        ["2026-13-01", "", "Att 张伟", "请假", "", ""],          # 日期错
        ["2026-11-22", "", "Nobody", "请假", "", ""],            # 没这个人
    ]).json()
    assert r["imported"] == 0 and [e["row"] for e in r["errors"]] == [3, 4, 5]
    assert grid(client, admin_h, teams["T1"], "2026-11-22", "2026-11-22")["cells"][str(ws["a"])]["2026-11-22"]["source"] == "default"

    r = _import(client, admin_h, [
        ["2026-11-22", "E100", "", "bolovanje", "", "flu"],
        ["23.11.2026", "", "att 张伟", "prisutan", "treća", "zamena"],
        ["2026-11-24", "", "Att 张伟", "absent", None, None],
    ]).json()
    assert (r["imported"], r["errors"]) == (3, [])
    cells = grid(client, admin_h, teams["T1"], "2026-11-22", "2026-11-24")["cells"]
    assert cells[str(ws["a"])]["2026-11-22"]["status"] == "sick"
    assert cells[str(ws["b"])]["2026-11-23"]["shift_kind"] == "night" and cells[str(ws["b"])]["2026-11-23"]["source"] == "import"
    assert cells[str(ws["b"])]["2026-11-24"]["status"] == "absent"


def test_template_downloads(client, admin_h, leader_h):
    """下载出勤月表（工厂的格式）：Year / Month、日期行、Sap No.，按系统出勤填好。班长（出勤权限本班组）不能下载。"""
    assert client.get("/api/attendance/template", headers=leader_h).status_code == 403
    r = client.get("/api/attendance/template", headers=admin_h, params={"month": "2026-11"})
    assert r.status_code == 200 and "2026-11" in r.headers["content-disposition"]
    ws = load_workbook(io.BytesIO(r.content)).worksheets[0]
    assert (ws["A1"].value, ws["C1"].value, ws["A2"].value, ws["C2"].value, ws["B3"].value) == ("Year", 2026, "Month", 11, "Sap No.")
    assert ws["C3"].value.startswith("=IF(MONTH(DATE($C$1,$C$2,COLUMN(A1)))") and ws["F1"].value.startswith("Note:")


def test_person_day(client, leader_h, ws):
    t = client.post("/api/tasks", headers=leader_h, json={
        "client_id": str(uuid.uuid4()), "content": "Person-day task", "lang": "en", "worker_ids": [ws["a"]],
        "recorded_at": "2026-11-21T10:00:00+01:00"}).json()
    r = client.get(f"/api/workers/{ws['a']}/day", headers=leader_h, params={"day": t["shift_date"]}).json()
    assert t["id"] in [x["id"] for x in r["tasks"]] and r["attendance"]["status"] is not None


def test_export(client, admin_h, leader_h, teams, ws):
    tk = client.post("/api/tasks", headers=leader_h, json={
        "client_id": str(uuid.uuid4()), "content": "导出测试：更换托辊", "lang": "zh", "worker_ids": [ws["a"], ws["b"]],
        "status": "done", "start_at": "2026-11-21T08:00:00+01:00", "end_at": "2026-11-21T10:30:00+01:00",
        "recorded_at": "2026-11-21T11:00:00+01:00"}).json()
    day = tk["shift_date"]
    assert client.post(f"/api/tasks/{tk['id']}/logs", headers=admin_h,
                       json={"content": "托辊轴承已换新", "lang": "zh"}).status_code == 201
    r = client.get("/api/export/tasks", headers=admin_h,
                   params={"start": day, "end": day, "team_id": teams["T1"], "lang": "sr"})
    assert r.status_code == 200 and "spreadsheetml" in r.headers["content-type"]
    wb = load_workbook(io.BytesIO(r.content))
    att_sheet = f"Prisustvo {day[5:7]}-{day[:4]}"  # 出勤：工厂的月表格式，每个月一张
    assert wb.sheetnames == ["Zadaci", "Opterećenje", att_sheet, "Dnevnik smene"]
    logs = list(wb["Dnevnik smene"].iter_rows(values_only=True))
    lg = dict(zip(logs[0], next(x for x in logs if x[0] == tk["id"])))
    assert lg["Sadržaj"] == "托辊轴承已换新" and lg["Opis posla"] == "导出测试：更换托辊"
    rows = list(wb["Zadaci"].iter_rows(values_only=True))
    hdr = rows[0]
    row = next(x for x in rows if x[0] == tk["id"])
    rec = dict(zip(hdr, row))
    assert rec["Opis posla"] == "导出测试：更换托辊"  # 没有译文时用原文
    assert rec["Sati"] == 2.5 and rec["Status"] == "Završeno" and "Att Petar" in rec["Učesnici"]
    assert rec["Početak"].hour == 8  # 工厂本地时间
    load = {x[0]: dict(zip(next(wb["Opterećenje"].iter_rows(values_only=True)), x))
            for x in wb["Opterećenje"].iter_rows(min_row=2, values_only=True) if x[0]}
    assert load["Att Petar"]["Ukupno sati"] >= 2.5 and load["Att Petar"]["Zadaci"] >= 1
    sh = wb[att_sheet]
    assert (sh["A1"].value, sh["C1"].value, sh["C2"].value) == ("Year", int(day[:4]), int(day[5:7]))
    row = next(r for r in sh.iter_rows(min_row=5, values_only=True) if r[0] == "Att Petar")
    d = int(day[8:])
    assert row[1] == "E100" and row[1 + d] in ("1", "2", "3", "/", "SL", "AL", "RW")  # 导出那天有内容
    assert all(v in (None, "") for k, v in enumerate(row[2:], start=1) if k != d)  # 时间段以外留空

    # 按人员导出
    r = client.get("/api/export/tasks", headers=admin_h, params={"start": day, "end": day, "worker_id": ws["b"]})
    wb = load_workbook(io.BytesIO(r.content))
    assert [x[0] for x in wb["人员工作量"].iter_rows(min_row=2, values_only=True) if x[0]][:1] == ["Att 张伟"]

    # 班长只能导出本班组
    assert client.get("/api/export/tasks", headers=leader_h,
                      params={"start": day, "end": day, "team_id": teams["T2"]}).status_code == 403
    assert client.get("/api/export/tasks", headers=leader_h, params={"start": day, "end": day}).status_code == 200
    logs = client.get("/api/audit", headers=admin_h, params={"entity": "export"}).json()["items"]
    assert len(logs) >= 3
