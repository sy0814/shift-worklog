"""设备台账：增改删、自动翻译、改原文重新翻译 / 改译文保留、任务关联设备、Excel 导入导出、权限。"""

import io
import uuid

from openpyxl import Workbook, load_workbook

from .conftest import login
from .test_translation import fake  # noqa: F401  （pytest fixture）


def test_create_translate_and_edit(client, admin_h, leader_h, fake):  # noqa: F811
    body = {"code": "BM-01", "name": {"zh": "1# 球磨机"}, "area": {"zh": "磨矿车间"}, "model": "MQY3245", "lang": "zh"}
    r = client.post("/api/equipment", headers=leader_h, json=body)  # 班长默认可以管设备
    assert r.status_code == 201, r.text
    e = client.get(f"/api/equipment/{r.json()['id']}", headers=leader_h).json()
    assert e["name"] == {"zh": "1# 球磨机", "sr": "[sr]1# 球磨机", "en": "[en]1# 球磨机"}
    assert e["area"]["en"] == "[en]磨矿车间" and e["translation_status"] == "done" and e["note"]["zh"] is None
    assert client.post("/api/equipment", headers=admin_h, json=body).status_code == 409  # 编号重复
    # 只改塞语译文 = 人工校对，不动其他语言
    r = client.patch(f"/api/equipment/{e['id']}", headers=admin_h, json={"name": e["name"] | {"sr": "Kuglični mlin 1"}})
    assert r.json()["name"] == {"zh": "1# 球磨机", "sr": "Kuglični mlin 1", "en": "[en]1# 球磨机"}
    # 改原文 → 其他语言重新翻译
    r = client.patch(f"/api/equipment/{e['id']}", headers=admin_h,
                     json={"name": {"zh": "1# 大球磨机", "sr": "Kuglični mlin 1", "en": "[en]1# 球磨机"}})
    e2 = client.get(f"/api/equipment/{e['id']}", headers=admin_h).json()
    assert e2["name"]["sr"] == "[sr]1# 大球磨机" and e2["name"]["en"] == "[en]1# 大球磨机"
    # 成员不能管设备，但能看
    m = client.post("/api/workers", headers=admin_h, json={"name": "Eq Member", "team_id": 1}).json()
    uid = client.put(f"/api/workers/{m['id']}/account", headers=admin_h, json={"password": "1111"}).json()["user_id"]
    mh = {"Authorization": "Bearer " + client.post("/api/auth/pin", json={"user_id": uid, "pin": "1111"}).json()["access_token"]}
    client.post("/api/auth/change-password", headers=mh, json={"old_password": "1111", "new_password": "2222"})
    assert client.post("/api/equipment", headers=mh, json=body | {"code": "X-1"}).status_code == 403
    assert any(x["code"] == "BM-01" for x in client.get("/api/equipment", headers=mh).json())


def test_task_links_equipment(client, admin_h, leader_h):
    e = client.post("/api/equipment", headers=admin_h, json={"code": "BC-07", "name": {"en": "Belt conveyor 7"}, "lang": "en"}).json()
    r = client.post("/api/tasks", headers=leader_h, json={"client_id": str(uuid.uuid4()), "content": "Check belt",
                                                         "lang": "en", "equipment_id": e["id"]})
    assert r.status_code == 201 and r.json()["equipment"]["code"] == "BC-07"
    tid = r.json()["id"]
    lst = client.get("/api/tasks", headers=leader_h, params={"equipment_id": e["id"]}).json()
    assert [t["id"] for t in lst["items"]] == [tid]
    d = client.get(f"/api/equipment/{e['id']}", headers=admin_h).json()
    assert (d["tasks_total"], d["tasks_open"]) == (1, 1) and d["last_task_date"]
    assert client.delete(f"/api/equipment/{e['id']}", headers=admin_h).status_code == 409  # 用过的只能停用
    assert client.patch(f"/api/equipment/{e['id']}", headers=admin_h, json={"is_active": False}).json()["is_active"] is False
    assert not any(x["id"] == e["id"] for x in client.get("/api/equipment", headers=admin_h).json())
    # 去掉关联
    r = client.patch(f"/api/tasks/{tid}", headers=leader_h, json={"equipment_id": None})
    assert r.json()["equipment"] is None
    assert client.post("/api/tasks", headers=leader_h, json={"client_id": str(uuid.uuid4()), "content": "x", "lang": "en",
                                                             "equipment_id": 999999}).status_code == 400


def _xlsx(rows):
    wb = Workbook()
    for r in rows:
        wb.active.append(r)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_import_export(client, admin_h, leader_h):
    data = _xlsx([["设备编号", "名称", "区域", "型号规格", "Naziv sr"],
                  ["CR-01", "颚式破碎机", "破碎车间", "PE600", "Čeljusna drobilica"],
                  ["CR-02", "圆锥破碎机", "破碎车间", "", ""]])
    up = lambda d, dry: client.post("/api/equipment/import/xlsx", headers=admin_h, data={"lang": "zh", "dry_run": str(dry).lower()},
                                    files={"file": ("e.xlsx", d)})
    r = up(data, True).json()
    assert (r["created"], r["applied"]) == (2, False)
    assert not any(x["code"] == "CR-01" for x in client.get("/api/equipment", headers=admin_h).json())
    r = up(data, False).json()
    assert (r["created"], r["applied"]) == (2, True)
    eq = {x["code"]: x for x in client.get("/api/equipment", headers=admin_h).json()}
    assert eq["CR-01"]["name"]["sr"] == "Čeljusna drobilica" and eq["CR-01"]["model"] == "PE600"
    # 再导一次：编号已有 → 更新；有一行错就全不导入
    bad = _xlsx([["设备编号", "名称"], ["CR-01", "颚式破碎机 A"], ["", "没有编号"]])
    r = up(bad, False).json()
    assert r["applied"] is False and r["errors"][0]["row"] == 3
    r = up(_xlsx([["设备编号", "型号规格"], ["CR-02", "GP100"]]), False).json()
    assert (r["updated"], r["created"]) == (1, 0)
    # 导出：三语列
    x = client.get("/api/equipment/export/xlsx", headers=admin_h, params={"lang": "en"})
    ws = load_workbook(io.BytesIO(x.content)).active
    head = [c.value for c in ws[1]]
    assert head[:4] == ["Equipment code", "Name zh", "Name sr", "Name en"]
    assert any(row[0].value == "CR-02" for row in ws.iter_rows(min_row=2))
    # 其他班组的班长也能管设备（设备不分班组）
    assert client.post("/api/equipment/import/xlsx", headers=login(client, "t2_leader1", "t2_leader1"),
                       data={"lang": "zh", "dry_run": "true"}, files={"file": ("e.xlsx", data)}).status_code == 200
