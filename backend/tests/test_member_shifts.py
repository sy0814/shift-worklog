"""不固定班组：成员被单独安排上班时，班组当天也算在班（合并显示、能分配任务）；其他成员不受影响。
自定义上班时间分两段的人：只在一个班次里显示，中间休息有提示。"""

from datetime import datetime, timedelta

from app.db import SessionLocal
from app.routers import duty as duty_router
from app.schedule_service import load_schedule

D = datetime(2031, 3, 5).date()  # 一个普通的周三


def _main_on(kind):
    with SessionLocal() as db:
        return load_schedule(db).main_team_on(D, kind).id


def test_manual_team_member_scheduled(client, admin_h, monkeypatch):
    t = client.post("/api/teams", headers=admin_h, json={"name_zh": "抢修组", "kind": "manual", "is_main": False}).json()
    a = client.post("/api/workers", headers=admin_h, json={"name": "Called In", "team_id": t["id"]}).json()
    b = client.post("/api/workers", headers=admin_h, json={"name": "Stays Home", "team_id": t["id"]}).json()
    # 没安排任何人：班组当天休息；给这个班组建任务也不会出错（归到当前班次）
    cal = lambda: client.get("/api/shifts/calendar", headers=admin_h, params={"start": str(D), "end": str(D)}).json()[0]
    assert cal()["shifts"][str(t["id"])] == "off"
    r = client.get("/api/assignable", headers=admin_h, params={"team_id": t["id"]})
    assert r.status_code == 200
    # 出勤页把一个人安排上白班
    r = client.put("/api/attendance/batch", headers=admin_h, json={"worker_ids": [a["id"]], "start": str(D), "end": str(D),
                                                                    "status": "present", "shift_kind": "day"})
    assert r.status_code == 200
    c = cal()
    assert c["shifts"][str(t["id"])] == "day" and t["id"] in c["by_members"]
    # 另一个成员不会因此被算成上班
    g = client.get("/api/attendance", headers=admin_h, params={"start": str(D), "end": str(D), "team_id": t["id"]}).json()
    assert g["cells"][str(a["id"])][str(D)]["status"] == "present"
    assert g["cells"][str(b["id"])][str(D)]["status"] == "off"
    # 白班的主班组那一组能分配到他；交接班里合并显示
    with SessionLocal() as db:
        sched = load_schedule(db)
        main = sched.main_team_on(D, "day")
        assert t["id"] in {x.id for x in sched.group_of(main, D, "day")}
    from app.routers.tasks import assignable_ids
    with SessionLocal() as db:
        ids = assignable_ids(db, load_schedule(db), main.id, D, "day")
    assert a["id"] in ids and b["id"] not in ids
    # 首页人员状态（白班 10:00）：在他自己的班组下面
    monkeypatch.setattr(duty_router, "local_now", lambda: datetime.combine(D, datetime.min.time()) + timedelta(hours=10))
    du = client.get("/api/duty", headers=admin_h).json()
    names = {x["team_id"]: [y["worker"]["name"] for y in x["workers"]] for x in du["teams"]}
    assert names.get(t["id"]) == ["Called In"]


def test_split_hours_shown_once_with_break(client, admin_h, monkeypatch):
    t = client.post("/api/teams", headers=admin_h, json={"name_zh": "分段组", "kind": "manual", "is_main": False}).json()
    w = client.post("/api/workers", headers=admin_h, json={"name": "Split Hours", "team_id": t["id"]}).json()
    start = D - timedelta(days=2)
    r = client.put(f"/api/workers/{w['id']}/schedule", headers=admin_h, json={
        "effective_from": str(start), "team_id": t["id"], "personal": True,
        "pattern": ["07:00-12:00,14:00-17:00"] * 7, "cycle_start": str(start)})
    assert r.status_code == 200, r.text

    def at(h, which="current"):
        monkeypatch.setattr(duty_router, "local_now", lambda: datetime.combine(D, datetime.min.time()) + timedelta(hours=h))
        du = client.get("/api/duty", headers=admin_h, params={"which": which}).json()
        rows = [y for x in du["teams"] for y in x["workers"] if y["worker"]["id"] == w["id"]]
        rows += [y for y in du["top"] if y["worker"]["id"] == w["id"]]
        return du["shift_kind"], rows

    k, rows = at(9)
    assert k == "day" and [r["status"] for r in rows] == ["idle"]
    _k, nxt = at(9, "next")  # 下一个班（中班）里也列出来、计入在岗，写「到 17:00」（2026-11-25 用户要求）
    assert [r["status"] for r in nxt] == ["idle"] and nxt[0]["overlap_until"].startswith(f"{D}T17:00")
    k, rows = at(13)  # 午休
    assert rows[0]["status"] == "off_hours" and rows[0]["back_at"].startswith(f"{D}T14:00")
    k, rows = at(16)  # 已经是中班时段，他 14-17 还在上班：只在当前班（中班）里出现一次
    assert k == "middle" and len(rows) == 1 and rows[0]["status"] == "idle"
    k, rows = at(18)  # 下班了
    assert k == "middle" and not rows


def test_early_start_in_night_shift(client, admin_h, monkeypatch):
    """06:00-11:00,14:00-17:00（算白班）：06-07 落在夜班里。夜班 04:00 时还没到点 → 休息中、06:00 上班，
    不能显示成空闲；06:30 才算在岗。"""
    t = client.post("/api/teams", headers=admin_h, json={"name_zh": "早到组", "kind": "manual", "is_main": False}).json()
    w = client.post("/api/workers", headers=admin_h, json={"name": "Early Bird", "team_id": t["id"]}).json()
    start = D - timedelta(days=2)
    r = client.put(f"/api/workers/{w['id']}/schedule", headers=admin_h, json={
        "effective_from": str(start), "team_id": t["id"], "personal": True,
        "pattern": ["06:00-11:00,14:00-17:00"] * 7, "cycle_start": str(start)})
    assert r.status_code == 200, r.text

    def at(h):
        monkeypatch.setattr(duty_router, "local_now", lambda: datetime.combine(D, datetime.min.time()) + timedelta(hours=h))
        du = client.get("/api/duty", headers=admin_h).json()
        rows = [y for x in du["teams"] for y in x["workers"] if y["worker"]["id"] == w["id"]]
        rows += [y for y in du["top"] if y["worker"]["id"] == w["id"]]
        return du["shift_kind"], rows

    k, rows = at(4)
    assert k == "night" and [r["status"] for r in rows] == ["off_hours"]
    assert rows[0]["back_at"].startswith(f"{D}T06:00")
    k, rows = at(6.5)
    assert k == "night" and [r["status"] for r in rows] == ["idle"]  # 已经在上班：在岗
    k, rows = at(9)
    assert k == "day" and [r["status"] for r in rows] == ["idle"]


def test_split_hours_assignable_in_next_shift(client, admin_h, monkeypatch):
    """白班 07-12、14-17 的人：中班的主班组也能给他安排任务（他 15-17 还在）。"""
    from app.routers import tasks as tasks_router

    with SessionLocal() as db:
        s = load_schedule(db)
        main = s.main_team_on(D, "day", s.team(1).dept)
        mid = s.main_team_on(D, "middle", s.team(1).dept)
    w = client.post("/api/workers", headers=admin_h, json={"name": "Split Assign", "team_id": main.id}).json()
    start = D - timedelta(days=2)
    assert client.put(f"/api/workers/{w['id']}/schedule", headers=admin_h, json={
        "effective_from": str(start), "team_id": main.id, "personal": True,
        "pattern": ["07:00-12:00,14:00-17:00"] * 7, "cycle_start": str(start)}).status_code == 200
    with SessionLocal() as db:
        s = load_schedule(db)
        assert w["id"] in tasks_router.assignable_ids(db, s, mid.id, D, "middle")
        assert w["id"] in tasks_router.assignable_ids(db, s, main.id, D, "day")  # 白班本来就能


PATTERNS = ["06:00-11:00,14:00-17:00", "07:00-12:00,14:00-17:00", "22:00-06:00", "13:00-21:00",
            "20:00-02:00,03:00-05:00", "05:00-09:00,18:00-22:00", "12:00-20:00", "23:00-03:00,07:00-11:00"]


def test_on_duty_iff_in_hours_all_day(client, admin_h, monkeypatch):
    """不变量：任何时刻，首页「当前班次」里这个人算在岗（空闲 / 忙碌）⇔ 他此刻真的在自己的时间段里；
    最多出现一次。每种写法、两天里每半小时都查一遍（只挑几个时间点的测试漏过了 06:00-11:00 那个 bug）。"""
    from app.work_hours import in_hours

    t = client.post("/api/teams", headers=admin_h, json={"name_zh": "全天检查组", "kind": "manual", "is_main": False}).json()
    start = D - timedelta(days=3)
    people = {}
    for i, p in enumerate(PATTERNS):
        w = client.post("/api/workers", headers=admin_h, json={"name": f"Inv {i}", "team_id": t["id"]}).json()
        r = client.put(f"/api/workers/{w['id']}/schedule", headers=admin_h, json={
            "effective_from": str(start), "team_id": t["id"], "personal": True, "pattern": [p] * 7,
            "cycle_start": str(start)})
        assert r.status_code == 200, (p, r.text)
        people[w["id"]] = p
    with SessionLocal() as db:
        sched = load_schedule(db)
    base = datetime.combine(D, datetime.min.time())
    bad = []
    for step in range(96):
        now = base + timedelta(minutes=30 * step)
        monkeypatch.setattr(duty_router, "local_now", lambda now=now: now)
        du = client.get("/api/duty", headers=admin_h).json()
        rows = [y for x in du["teams"] for y in x["workers"]] + du["top"] + du["managers"]
        for wid, p in people.items():
            mine = [r["status"] for r in rows if r["worker"]["id"] == wid]
            working = any(in_hours(sched, p, now.date() + timedelta(days=k), now) for k in (-1, 0, 1))
            on = [s for s in mine if s in ("idle", "busy")]
            if len(mine) > 1 or (len(on) == 1) != working:
                bad.append(f"{now:%m-%d %H:%M} {p}: {mine} working={working}")
    assert not bad, "\n".join(bad[:20])
