import io
import uuid
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest
from PIL import Image

from .conftest import login


def uid():
    return str(uuid.uuid4())


@pytest.fixture(scope="module")
def teams(client, admin_h):
    return {t["code"]: t["id"] for t in client.get("/api/teams", headers=admin_h).json()}


@pytest.fixture(scope="module")
def workers(client, admin_h, teams):
    r = client.post("/api/workers/bulk", headers=admin_h,
                    json={"names": ["Petar", "Jovan", "张三", "Petar"], "team_id": teams["T1"]})
    assert r.status_code == 201
    ws = r.json()
    assert [w["name"] for w in ws] == ["Petar", "Jovan", "张三"]  # 重复名字去掉
    return [w["id"] for w in ws]


@pytest.fixture(scope="module")
def t2_h(client):
    return login(client, "t2_leader1", "t2_leader1")


def new_task(client, h, **kw):
    body = {"client_id": uid(), "content": "检查 3# 球磨机润滑油压", "lang": "zh"} | kw
    r = client.post("/api/tasks", headers=h, json=body)
    assert r.status_code == 201, r.text
    return r.json()


def jpeg(exif_time: str | None = None, offset: str | None = None, size=(2400, 1200), orientation=None):
    img = Image.new("RGB", size, (200, 30, 30))
    exif = Image.Exif()
    if exif_time:
        sub = exif.get_ifd(0x8769)
        sub[36867] = exif_time
        if offset:
            sub[36881] = offset
    if orientation:
        exif[274] = orientation
    buf = io.BytesIO()
    img.save(buf, "JPEG", exif=exif.tobytes())
    return buf.getvalue()


def upload(client, h, task_id, data, **form):
    return client.post(f"/api/tasks/{task_id}/attachments", headers=h,
                       files={"file": ("p.jpg", data, "image/jpeg")},
                       data={"client_id": uid()} | form)


def test_create_task_leader(client, leader_h, teams, workers):
    t = new_task(client, leader_h, worker_ids=workers[:2], team_id=teams["T3"])
    assert t["team_id"] == teams["T1"]  # 班长只能建本班组任务，忽略传入的 team_id
    assert t["content"]["zh"] and t["content"]["sr"] is None
    assert t["translation_status"] == "pending"
    assert t["created_by_name"] == "t1_leader1" and t["updated_by_name"] == "t1_leader1"
    assert [w["name"] for w in t["workers"]] == ["Petar", "Jovan"]
    assert t["status"] == "not_started" and t["can_edit"]


def test_create_is_idempotent(client, leader_h):
    cid = uid()
    a = new_task(client, leader_h, client_id=cid)
    b = client.post("/api/tasks", headers=leader_h, json={"client_id": cid, "content": "x", "lang": "zh"})
    assert b.status_code == 409  # 同一 client_id、不同内容 → 拒绝
    c = client.post("/api/tasks", headers=leader_h,
                    json={"client_id": cid, "content": a["content"]["zh"], "lang": "zh"})
    assert c.status_code == 201 and c.json()["id"] == a["id"]  # 真正的重试 → 返回原任务


def test_admin_must_choose_team(client, admin_h, teams):
    r = client.post("/api/tasks", headers=admin_h, json={"client_id": uid(), "content": "x", "lang": "en"})
    assert r.status_code == 400
    t = new_task(client, admin_h, team_id=teams["DAY"], lang="en", content="Replace conveyor belt idler")
    assert t["team_id"] == teams["DAY"]


def test_offline_recorded_at_sets_shift(client, admin_h):
    # 离线草稿昨天 23:30（工厂时区）由当晚上夜班的班组录入，今天才同步 → 归属昨天的夜班
    from app.db import SessionLocal
    from app.schedule_service import load_schedule
    tz = ZoneInfo("Europe/Belgrade")
    yday = datetime.now(tz).date() - timedelta(days=1)
    with SessionLocal() as db:
        night_team = load_schedule(db).rotating_team_on(yday, "night").id
    rec = datetime.combine(yday, time(23, 30), tz)
    t = new_task(client, admin_h, team_id=night_team, recorded_at=rec.isoformat())
    assert (t["shift_date"], t["shift_kind"]) == (yday.isoformat(), "night")
    # 早于 30 天的录入时间不可信，按同步时间算
    old = new_task(client, admin_h, team_id=night_team, recorded_at="2020-01-01T10:00:00+01:00")
    assert old["recorded_at"][:4] != "2020"


def test_other_team_cannot_edit(client, leader_h, t2_h):
    t = new_task(client, leader_h)
    other = client.get(f"/api/tasks/{t['id']}", headers=t2_h).json()
    assert other["can_edit"] is False
    assert client.patch(f"/api/tasks/{t['id']}", headers=t2_h, json={"content": "x"}).status_code == 403
    assert client.post(f"/api/tasks/{t['id']}/status", headers=t2_h, json={"status": "done"}).status_code == 403


def test_update_content_and_workers_audited(client, leader_h, workers):
    t = new_task(client, leader_h, worker_ids=[workers[0]])
    r = client.patch(f"/api/tasks/{t['id']}", headers=leader_h, json={
        "content": "Proveriti pritisak ulja", "lang": "sr", "worker_ids": [workers[1], workers[2]],
        "leftover": "Nedostaje filter", "start_at": "2026-11-22T08:00:00+01:00",
        "end_at": "2026-11-22T07:00:00+01:00"})
    assert r.status_code == 400  # 结束早于开始
    r = client.patch(f"/api/tasks/{t['id']}", headers=leader_h, json={
        "content": "Proveriti pritisak ulja", "lang": "sr", "worker_ids": [workers[1], workers[2]],
        "leftover": "Nedostaje filter"})
    body = r.json()
    assert body["source_lang"] == "sr" and body["content"] == {"zh": None, "sr": "Proveriti pritisak ulja", "en": None}
    assert body["leftover"]["sr"] == "Nedostaje filter"
    assert [w["id"] for w in body["workers"]] == [workers[1], workers[2]]
    hist = client.get(f"/api/tasks/{t['id']}/history", headers=leader_h).json()
    fields = {h["field"] for h in hist}
    assert {"content_zh", "content_sr", "source_lang", "workers", "leftover_sr"} <= fields
    wh = next(h for h in hist if h["field"] == "workers")
    assert "Petar" in wh["old_value"] and "张三" in wh["new_value"]
    assert all(h["user_name"] == "t1_leader1" for h in hist)
    # 相同内容再提交不产生新记录
    client.patch(f"/api/tasks/{t['id']}", headers=leader_h, json={"content": "Proveriti pritisak ulja", "lang": "sr"})
    assert len(client.get(f"/api/tasks/{t['id']}/history", headers=leader_h).json()) == len(hist)


def test_status_flow(client, leader_h):
    t = new_task(client, leader_h)
    s = lambda st: client.post(f"/api/tasks/{t['id']}/status", headers=leader_h, json={"status": st})
    r = s("in_progress").json()
    assert r["status"] == "in_progress" and r["start_at"]
    r = s("done").json()
    assert r["status"] == "done" and r["end_at"] and r["confirmed_by_name"] == "t1_leader1"
    assert s("not_started").status_code == 409  # done 只能重新打开为 in_progress
    r = s("in_progress").json()
    assert r["end_at"] is None and r["confirmed_by"] is None
    hist = client.get(f"/api/tasks/{t['id']}/history", headers=leader_h).json()
    assert [h["new_value"] for h in hist if h["field"] == "status"] == ["in_progress", "done", "in_progress"]


def test_create_done_directly(client, leader_h):
    t = new_task(client, leader_h, status="done")
    assert t["status"] == "done" and t["start_at"] and t["end_at"] and t["confirmed_by_name"]


def test_list_filters(client, leader_h, teams, workers):
    new_task(client, leader_h, content="Zameniti ležaj pumpe", lang="sr", worker_ids=[workers[2]])
    r = client.get("/api/tasks", headers=leader_h, params={"q": "ležaj"}).json()
    assert r["total"] == 1
    r = client.get("/api/tasks", headers=leader_h, params={"worker_id": workers[2]}).json()
    assert r["total"] >= 1 and all(any(w["id"] == workers[2] for w in t["workers"]) for t in r["items"])
    r = client.get("/api/tasks", headers=leader_h, params={"team_id": teams["DAY"]}).json()
    assert all(t["team_id"] == teams["DAY"] for t in r["items"])
    r = client.get("/api/tasks", headers=leader_h, params=[("status", "done"), ("status", "in_progress")]).json()
    assert all(t["status"] in ("done", "in_progress") for t in r["items"])


def test_photo_exif_time_and_files(client, leader_h, t2_h):
    t = new_task(client, leader_h)
    r = upload(client, leader_h, t["id"], jpeg("2026:11:20 09:15:30", orientation=6))
    assert r.status_code == 201, r.text
    a = r.json()
    assert a["taken_at_source"] == "exif"
    # 无时区信息按工厂时区（贝尔格莱德 UTC+1）→ 08:15:30Z
    assert a["taken_at"].startswith("2026-11-20T08:15:30")
    assert (a["width"], a["height"]) == (1200, 2400)  # 已按 EXIF 方向转正
    thumb = client.get(a["url_thumb"])
    assert thumb.status_code == 200 and thumb.headers["content-type"] == "image/jpeg"
    assert max(Image.open(io.BytesIO(thumb.content)).size) == 400
    view = Image.open(io.BytesIO(client.get(a["url_view"]).content))
    assert view.size == (800, 1600)
    assert client.get(a["url_original"]).content[:2] == b"\xff\xd8"
    bad = a["url_thumb"].split("?")[0] + "?t=forged"
    assert client.get(bad).status_code == 404
    # 别的班组不能上传
    assert upload(client, t2_h, t["id"], jpeg()).status_code == 403


def test_photo_exif_with_offset(client, leader_h):
    t = new_task(client, leader_h)
    a = upload(client, leader_h, t["id"], jpeg("2026:11:20 09:15:30", "+08:00")).json()
    assert a["taken_at"].startswith("2026-11-20T01:15:30")


def test_photo_time_fallbacks(client, leader_h):
    t = new_task(client, leader_h)
    ms = int(datetime(2026, 11, 19, 12, 0, tzinfo=timezone.utc).timestamp() * 1000)
    a = upload(client, leader_h, t["id"], jpeg(), last_modified=ms).json()
    assert a["taken_at_source"] == "file" and a["taken_at"].startswith("2026-11-19T12:00")
    b = upload(client, leader_h, t["id"], jpeg()).json()
    assert b["taken_at_source"] == "upload"
    # 未来时间的文件修改时间不可信
    future = int((datetime.now(timezone.utc) + timedelta(days=2)).timestamp() * 1000)
    c = upload(client, leader_h, t["id"], jpeg(), last_modified=future).json()
    assert c["taken_at_source"] == "upload"


def test_photo_client_exif(client, leader_h):
    # 手机压缩后图片里没有 EXIF，时间由前端单独带上
    t = new_task(client, leader_h)
    a = upload(client, leader_h, t["id"], jpeg(), exif_datetime="2026:11:20 09:15:30",
               last_modified=int(datetime(2026, 11, 21, tzinfo=timezone.utc).timestamp() * 1000)).json()
    assert a["taken_at_source"] == "exif" and a["taken_at"].startswith("2026-11-20T08:15:30")
    b = upload(client, leader_h, t["id"], jpeg(), exif_datetime="2026:11:20 09:15:30", exif_offset="+08:00").json()
    assert b["taken_at"].startswith("2026-11-20T01:15:30")
    # 文件自带 EXIF 优先于前端传的
    c = upload(client, leader_h, t["id"], jpeg("2026:11:19 07:00:00"), exif_datetime="2026:11:20 09:15:30").json()
    assert c["taken_at"].startswith("2026-11-19T06:00:00")
    # 格式错误的忽略
    d = upload(client, leader_h, t["id"], jpeg(), exif_datetime="garbage").json()
    assert d["taken_at_source"] == "upload"


def test_photo_idempotent_and_delete(client, leader_h):
    t = new_task(client, leader_h)
    cid = uid()
    data = jpeg("2026:11:20 10:00:00")
    a = upload(client, leader_h, t["id"], data, client_id=cid).json()
    b = upload(client, leader_h, t["id"], data, client_id=cid).json()
    assert a["id"] == b["id"]
    assert len(client.get(f"/api/tasks/{t['id']}", headers=leader_h).json()["attachments"]) == 1
    assert client.delete(f"/api/attachments/{a['id']}", headers=leader_h).status_code == 204
    assert client.get(f"/api/tasks/{t['id']}", headers=leader_h).json()["attachments"] == []
    hist = client.get(f"/api/tasks/{t['id']}/history", headers=leader_h).json()
    assert [h["action"] for h in hist if h["field"] == "attachments"] == ["attach", "detach"]


def test_reject_non_image(client, leader_h):
    t = new_task(client, leader_h)
    r = client.post(f"/api/tasks/{t['id']}/attachments", headers=leader_h,
                    files={"file": ("x.jpg", b"not an image", "image/jpeg")}, data={"client_id": uid()})
    assert r.status_code == 400


def test_workers_admin_only(client, leader_h):
    assert client.get("/api/workers", headers=leader_h).status_code == 200
    assert client.post("/api/workers", headers=leader_h, json={"name": "x"}).status_code == 403
