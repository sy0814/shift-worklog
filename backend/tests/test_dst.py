"""夏令时（工厂时区 Europe/Belgrade）：
  2026-03-29 02:00 → 03:00（少 1 小时）：3-28 的夜班实际只有 7 小时
  2026-10-25 03:00 → 02:00（多 1 小时）：10-24 的夜班实际有 9 小时
规则：班次划分、巡查时间按当地钟点；工时、加班时长按真实经过的时间算。
注意 Python 的坑：两个带同一个时区（ZoneInfo）的时间相减，算的是钟面差，不是真实经过的时间；要先转成 UTC 再减。
"""

import io
import uuid
from datetime import date, datetime, time, timezone

import pytest
from openpyxl import load_workbook

from app.config import get_settings
from app.db import SessionLocal
from app.inspection_schedule import Rule, next_occurrence
from app.inspection_service import to_utc
from app.schedule_service import load_schedule, slot

SPRING, FALL = date(2026, 3, 28), date(2026, 10, 24)
UTC = timezone.utc


def hours(a: datetime, b: datetime) -> float:
    return (b.astimezone(UTC) - a.astimezone(UTC)).total_seconds() / 3600


@pytest.fixture(scope="module")
def teams(client, admin_h):
    return {t["code"]: t["id"] for t in client.get("/api/teams", headers=admin_h).json()}


def test_timezone_is_belgrade():
    assert str(get_settings().tz) == "Europe/Belgrade"


def test_night_shift_real_length(client):
    with SessionLocal() as db:
        sched = load_schedule(db)
    assert hours(*(lambda s: (s.start, s.end))(slot(sched, SPRING, "night"))) == 7
    assert hours(*(lambda s: (s.start, s.end))(slot(sched, FALL, "night"))) == 9
    assert hours(*(lambda s: (s.start, s.end))(slot(sched, SPRING, "day"))) == 8  # 白班不跨切换时刻


def test_shift_at_during_repeated_hour(client):
    """10-25 02:30 这个钟点出现两次，两次都属于 10-24 的夜班。"""
    with SessionLocal() as db:
        sched = load_schedule(db)
    assert sched.shift_at(datetime(2026, 10, 25, 2, 30)) == (FALL, "night")
    assert sched.shift_at(datetime(2026, 3, 29, 3, 30)) == (SPRING, "night")


def test_export_hours_across_dst(client, admin_h, leader_h, teams):
    """导出的工时 = 真实经过的时间：3-28 夜班 23:00 → 07:00 是 7 小时，10-24 是 9 小时。"""
    cases = [("2026-03-28T23:00:00+01:00", "2026-03-29T07:00:00+02:00", 7.0),
             ("2026-10-24T23:00:00+02:00", "2026-10-25T07:00:00+01:00", 9.0)]
    for start, end, want in cases:
        t = client.post("/api/tasks", headers=leader_h, json={
            "client_id": str(uuid.uuid4()), "content": f"DST {want}", "lang": "en", "status": "done",
            "start_at": start, "end_at": end, "recorded_at": end}).json()
        d = t["shift_date"]
        r = client.get("/api/export/tasks", headers=admin_h, params={"start": d, "end": d, "team_id": teams["T1"], "lang": "en"})
        rows = list(load_workbook(io.BytesIO(r.content))["Tasks"].iter_rows(values_only=True))
        rec = dict(zip(rows[0], next(x for x in rows if x[0] == t["id"])))
        assert rec["Hours"] == want, (start, end, rec["Hours"])


def test_overtime_hours_across_dst(client, admin_h, teams):
    """中班 23:00 下班、加班到次日 03:30：3-28 那晚真实 3.5 小时，10-24 那晚真实 5.5 小时。"""
    w = client.post("/api/workers", headers=admin_h, json={"name": "DST Overtime", "team_id": teams["T1"]}).json()
    for d, want in ((SPRING, 3.5), (FALL, 5.5)):
        r = client.post("/api/overtime", headers=admin_h, json={
            "day": str(d), "shift_kind": "middle", "worker_ids": [w["id"]], "until": "03:30"})
        assert r.status_code == 201, r.text
        assert r.json()[0]["hours"] == want, (d, r.json())
        listed = client.get("/api/overtime", headers=admin_h, params={"start": str(d), "end": str(d)}).json()
        assert next(x for x in listed if x["worker_id"] == w["id"])["hours"] == want
    # 人员加班合计（导出、AI 分析用的也是它）
    from app.models import Worker
    from app.overtime_service import hours_by_worker
    with SessionLocal() as db:
        total = hours_by_worker(db, SPRING, FALL, [db.get(Worker, w["id"])])
    assert total[w["id"]] == 9.0


def test_inspection_daily_at_night_once_per_day(client):
    """每天 02:30 的巡查：3-29 没有 02:30 这个钟点（按 03:30 触发），10-25 有两次 02:30（只触发第一次）；
    每天都只派一次。"""
    rule = Rule(kind="daily", at_time=time(2, 30), start_date=date(2026, 1, 1))
    with SessionLocal() as db:
        sched = load_schedule(db)
    spring = next_occurrence(rule, datetime(2026, 3, 28, 12, 0), sched)
    assert spring == datetime(2026, 3, 29, 2, 30)
    assert to_utc(spring) == datetime(2026, 3, 29, 1, 30, tzinfo=UTC)  # = 当地 03:30（夏令时）
    assert next_occurrence(rule, spring, sched) == datetime(2026, 3, 30, 2, 30)
    fall = next_occurrence(rule, datetime(2026, 10, 24, 12, 0), sched)
    assert fall == datetime(2026, 10, 25, 2, 30)
    assert to_utc(fall) == datetime(2026, 10, 25, 0, 30, tzinfo=UTC)  # 第一次 02:30（夏令时）
    assert next_occurrence(rule, fall, sched) == datetime(2026, 10, 26, 2, 30)  # 钟点重复那一小时不会再派一次
