"""导入工厂的出勤月表（SSZM 那种）：一行一个人（Sap No. = 工号），一列一天；1 / 2 / 3 = 白 / 中 / 夜（夜班记在下班那天），
/ = 休息，其余是缩写。日期按列的顺序算（表头数字可能写错），用星期那一行核对月份；和排班一样的不记，不一样的记成例外；
认不出的格子、找不到的工号 → 整表不导入。"""

import io
from datetime import date, timedelta

import pytest
from openpyxl import Workbook

from app import attendance_service as att
from app.shifts import Schedule, day_team, rotating

DEC = [date(2026, 12, 1) + timedelta(days=i) for i in range(31)]
S = Schedule(teams=(rotating(1, 4), day_team(5)))
CODE = {"day": 1, "middle": 2, "night": 3, "off": "/"}


def planned(team, d):
    return CODE[S.shift_of(team, d)]


@pytest.fixture(scope="module")
def teams(client, admin_h):
    return {t["code"]: t["id"] for t in client.get("/api/teams", headers=admin_h).json()}


@pytest.fixture(scope="module")
def ws(client, admin_h, teams):
    mk = lambda name, no, team: client.post("/api/workers", headers=admin_h, json={
        "name": name, "employee_no": no, "team_id": teams[team]}).json()["id"]
    return {"s1": mk("Sheet A", "10700001", "T1"), "s2": mk("Sheet B", "10700002", "T1"), "d1": mk("Sheet Day", "10700003", "DAY")}


def sheet(rows, days=DEC, header_typo=True):
    """和工厂的表一样：第 1 行说明，第 2 行 DayDate / Sap No. / 日期数字（有笔误），第 3 行星期，空行隔开各班组。"""
    wb = Workbook()
    sh = wb.active
    sh.append(["Note: please follow the following rules … Annual leave=AL; Sick leave=SL …"])
    nums = [d.day for d in days]
    if header_typo:
        nums[25], nums[27] = 28, 24
    sh.append(["DayDate", "Sap No.", *nums, ""])
    sh.append(["Name", None, *[d.strftime("%a") for d in days], ""])
    for r in rows:
        sh.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def imp(client, h, data, month="2026-12"):
    return client.post("/api/attendance/import", headers=h, data={"month": month},
                       files={"file": ("SSZM.xlsx", data, "application/octet-stream")})


def cells(client, h, wid, team_id, start="2026-12-01", end="2026-12-31"):
    g = client.get("/api/attendance", headers=h, params={"team_id": team_id, "start": start, "end": end}).json()
    return g["cells"][str(wid)]


def test_sheet_cell():
    assert att.sheet_cell("1-12h") == att.sheet_cell("1-8H") == ("present", "day", None)
    assert att.sheet_cell("3-10h") == ("present", "night", None) and att.sheet_cell("4-8h") == "invalid"
    assert att.sheet_cell(1) == ("present", "day", None) and att.sheet_cell(3.0) == ("present", "night", None)
    assert att.sheet_cell("2.") == att.sheet_cell("2·") == ("present", "middle", None)
    assert att.sheet_cell("/") == ("off", None, None) and att.sheet_cell("") is None and att.sheet_cell(None) is None
    assert att.sheet_cell("al") == ("leave", None, "AL") and att.sheet_cell("PLBD") == ("leave", None, "PLBD")
    assert att.sheet_cell("SLI") == ("sick", None, "SLI") and att.sheet_cell("PH") == ("off", None, "PH")
    assert att.sheet_cell("EH") == ("present", None, "EH") and att.sheet_cell("RW") == ("absent", None, "RW")
    assert att.sheet_cell("笋") == "invalid" and att.sheet_cell("4") == "invalid"


def test_import_month_sheet(client, admin_h, leader_h, teams, ws):
    t1, day = S.teams
    a = [planned(t1, d) for d in DEC]
    a[2], a[3] = "AL", "2."  # 12-03 休息日记了年假；12-04 夜班改上中班
    b = [planned(t1, d) for d in DEC]
    b[0], b[1], b[6] = "SL", "BT", "EH"
    c = [planned(day, d) for d in DEC]
    c[4], c[7], c[8], c[9] = 1, "PH", "PLW", ""  # 12-05 周六来上白班；12-08 法定假；12-09 带薪婚假；12-10 空格子不改
    # 以前手工改过的：12-05 病假（表里是照常的夜班 → 清掉）
    client.put("/api/attendance", headers=admin_h, json={"worker_id": ws["s1"], "day": "2026-12-05", "status": "sick"})
    data = sheet([["", 10700001, *a, ""], ["", "10700002", *b, ""], ["", "", *[""] * 31, ""],
                  ["", 10700003, *c, ""]])
    assert imp(client, leader_h, data).status_code == 403
    r = imp(client, admin_h, data)
    assert r.status_code == 200, r.text
    out = r.json()
    assert out["errors"] == [] and (out["people"], out["days"], out["imported"], out["cleared"]) == (3, 31, 8, 1)

    s1 = cells(client, admin_h, ws["s1"], teams["T1"])
    assert (s1["2026-12-03"]["status"], s1["2026-12-03"]["code"], s1["2026-12-03"]["source"]) == ("leave", "AL", "import")
    assert (s1["2026-12-04"]["status"], s1["2026-12-04"]["shift_kind"], s1["2026-12-04"]["code"]) == ("present", "middle", None)
    assert s1["2026-12-05"]["source"] == "default" and s1["2026-12-05"]["shift_kind"] == "night"  # 旧的病假清掉了
    assert s1["2026-12-01"]["source"] == "default"  # 和排班一样的不记
    s2 = cells(client, admin_h, ws["s2"], teams["T1"])
    assert [(s2[d]["status"], s2[d]["code"]) for d in ("2026-12-01", "2026-12-02")] == [("sick", "SL"), ("leave", "BT")]
    assert (s2["2026-12-07"]["status"], s2["2026-12-07"]["shift_kind"], s2["2026-12-07"]["code"]) == ("present", "day", "EH")
    d1 = cells(client, admin_h, ws["d1"], teams["DAY"])
    assert (d1["2026-12-05"]["status"], d1["2026-12-05"]["shift_kind"]) == ("present", "day")
    assert [(d1[d]["status"], d1[d]["code"]) for d in ("2026-12-08", "2026-12-09")] == [("off", "PH"), ("leave", "PLW")]
    assert d1["2026-12-10"]["source"] == "default"
    # 同一张表再导一次：什么都不变
    again = imp(client, admin_h, data).json()
    assert (again["imported"], again["cleared"]) == (0, 0)


def test_import_month_sheet_errors(client, admin_h, ws):
    t1 = S.teams[0]
    a = [planned(t1, d) for d in DEC]
    a[10] = "笋"
    data = sheet([["", 10700001, *a, ""], ["", 99999999, *a[:10], 1, *a[11:], ""]])
    r = imp(client, admin_h, data).json()
    msgs = [e["message"] for e in r["errors"]]
    assert r["imported"] == 0 and len(msgs) == 2
    assert "12-11" in msgs[0] and "笋" in msgs[0] and "99999999" in msgs[1]
    # 月份选错了：星期对不上
    ok = sheet([["", 10700001, *[planned(t1, d) for d in DEC], ""]])
    r = imp(client, admin_h, ok, month="2027-12").json()
    assert r["imported"] == 0 and "月份" in r["errors"][0]["message"]
    # 天数不对（11 月只有 30 天，表里有 31 天）
    r = imp(client, admin_h, ok, month="2026-11").json()
    assert r["errors"] and r["imported"] == 0
    # 没选月份
    assert imp(client, admin_h, ok, month="").status_code == 400


def test_new_factory_layout_and_roundtrip(client, admin_h, teams, ws):
    """工厂新的表：第 1、2 行 Year / Month，第 3 行日期（公式），A 列姓名、B 列 Sap No.；1-12h 只按那个班算；
    没填 Sap No. 的按姓名。系统下载的月表原样导回去，什么都不变。"""
    from openpyxl import load_workbook

    r = client.get("/api/attendance/template", headers=admin_h, params={"month": "2027-01", "team_id": teams["T1"]})
    wb = load_workbook(io.BytesIO(r.content))
    sh = wb.worksheets[0]
    assert sh["C1"].value == 2027 and sh["C2"].value == 1
    again = client.post("/api/attendance/import", headers=admin_h, data={"month": "2026-05"},  # 页面上选错了月份也没关系
                        files={"file": ("t.xlsx", r.content, "application/octet-stream")}).json()
    assert again["errors"] == [] and again["month"] == "2027-01" and (again["imported"], again["cleared"]) == (0, 0)
    assert again["people"] >= 2 and again["days"] == 31
    # 改几格再导：1-12h = 白班；Sheet A 去掉工号只留姓名
    rows = {c.value: c.row for c in sh["B"] if c.value in (10700001, 10700002)}
    a, b = rows[10700001], rows[10700002]
    t1 = S.teams[0]
    day5 = date(2027, 1, 5)
    sh.cell(a, 2).value = None  # 只按姓名
    sh.cell(a, 2 + 5).value = "1-12h" if planned(t1, day5) != 1 else "2-12h"
    sh.cell(b, 2 + 6).value = "PLD"
    buf = io.BytesIO()
    wb.save(buf)
    out = client.post("/api/attendance/import", headers=admin_h,
                      files={"file": ("t.xlsx", buf.getvalue(), "application/octet-stream")}).json()
    assert out["errors"] == [] and out["imported"] == 2, out
    s1 = cells(client, admin_h, ws["s1"], teams["T1"], "2027-01-01", "2027-01-31")
    assert s1["2027-01-05"]["status"] == "present" and s1["2027-01-05"]["code"] is None
    assert s1["2027-01-05"]["shift_kind"] == ("day" if planned(t1, day5) != 1 else "middle")
    s2 = cells(client, admin_h, ws["s2"], teams["T1"], "2027-01-01", "2027-01-31")
    assert (s2["2027-01-06"]["status"], s2["2027-01-06"]["code"]) == ("leave", "PLD")
    # 下载回来：改过的格子写回原样的缩写
    r = client.get("/api/attendance/template", headers=admin_h, params={"month": "2027-01", "team_id": teams["T1"]})
    sh = load_workbook(io.BytesIO(r.content)).worksheets[0]
    assert next(x for x in sh.iter_rows(min_row=5, values_only=True) if x[1] == 10700002)[2 + 6 - 1] == "PLD"


def test_long_filename(client, admin_h):
    """手机上的文件名常常很长（超过留痕 entity_id 的 50 个字符）：PostgreSQL 上以前直接 500「请求失败」。"""
    t1 = S.teams[0]
    data = sheet([["", 10700001, *[planned(t1, d) for d in DEC], ""]])
    name = "出勤表 SSZM 2026年12月 电工车间 最终版 已核对 (1) - 副本 - 副本 - 副本 - 副本.xlsx" * 2
    r = client.post("/api/attendance/import", headers=admin_h, data={"month": "2026-12"},
                    files={"file": (name, data, "application/octet-stream")})
    assert r.status_code == 200 and r.json()["errors"] == [], r.text
