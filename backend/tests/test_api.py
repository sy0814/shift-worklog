
import pytest
from sqlalchemy.exc import DBAPIError

from app.db import engine
from sqlalchemy import text

from .conftest import login


def test_login_wrong_password(client):
    r = client.post("/api/auth/login", data={"username": "admin", "password": "x"})
    assert r.status_code == 401


def test_requires_auth(client):
    assert client.get("/api/teams").status_code == 401


def test_teams(client, leader_h):
    teams = client.get("/api/teams", headers=leader_h).json()
    assert [t["code"] for t in teams] == ["T1", "T2", "T3", "T4", "DAY"]


def test_leader_cannot_manage_users(client, leader_h):
    assert client.get("/api/users", headers=leader_h).status_code == 403
    assert client.get("/api/audit", headers=leader_h).status_code == 403


def test_admin_creates_leader_and_audit(client, admin_h):
    teams = {t["code"]: t["id"] for t in client.get("/api/teams", headers=admin_h).json()}
    r = client.post("/api/users", headers=admin_h, json={
        "username": "t1_leader2", "password": "secret1", "full_name": "Marko",
        "role": "leader", "team_id": teams["T1"]})
    assert r.status_code == 201, r.text
    uid = r.json()["id"]
    r = client.patch(f"/api/users/{uid}", headers=admin_h, json={"full_name": "Marko P."})
    assert r.json()["full_name"] == "Marko P."
    logs = client.get("/api/audit", headers=admin_h,
                      params={"entity": "user", "entity_id": str(uid)}).json()
    assert {(l["action"], l["field"]) for l in logs} >= {("create", None), ("update", "full_name")}
    upd = next(l for l in logs if l["field"] == "full_name")
    assert (upd["old_value"], upd["new_value"]) == ("Marko", "Marko P.")
    login(client, "t1_leader2", "secret1")


def test_leader_requires_team(client, admin_h):
    r = client.post("/api/users", headers=admin_h, json={
        "username": "noteam", "password": "secret1", "full_name": "x", "role": "leader"})
    assert r.status_code == 400


def test_admin_cannot_disable_self(client, admin_h):
    me = client.get("/api/auth/me", headers=admin_h).json()
    r = client.patch(f"/api/users/{me['id']}", headers=admin_h, json={"is_active": False})
    assert r.status_code == 400


def test_calendar(client, leader_h):
    days = client.get("/api/shifts/calendar", headers=leader_h,
                      params={"start": "2026-11-21", "end": "2026-11-21"}).json()
    teams = {t["code"]: str(t["id"]) for t in client.get("/api/teams", headers=leader_h).json()}
    s = days[0]["shifts"]
    assert (s[teams["T1"]], s[teams["T2"]], s[teams["T3"]], s[teams["T4"]], s[teams["DAY"]]) == \
        ("day", "middle", "night", "off", "off")


def test_shifts_now(client, leader_h):
    r = client.get("/api/shifts/now", headers=leader_h)
    assert r.status_code == 200
    body = r.json()
    assert body["current"]["team_ids"] and body["next"]["team_ids"]


def test_config_validation(client, admin_h):
    teams = {t["code"]: t["id"] for t in client.get("/api/teams", headers=admin_h).json()}
    bad = {"base_date": "2026-11-01", "day_start": "07:00", "middle_start": "15:00",
           "night_start": "23:00",
           "offsets": {teams["T1"]: 4, teams["T2"]: 5, teams["T3"]: 0, teams["T4"]: 2}}
    assert client.put("/api/shifts/config", headers=admin_h, json=bad).status_code == 400


def test_holiday_crud(client, admin_h, leader_h):
    assert client.put("/api/holidays/2026-12-25", headers=leader_h, json={"day": "2026-12-25"}).status_code == 403
    assert client.put("/api/holidays/2026-12-25", headers=admin_h,
                      json={"day": "2026-12-25", "name": "Christmas"}).status_code == 200
    assert client.get("/api/holidays", headers=admin_h, params={"year": 2026}).json()[0]["name"] == "Christmas"
    assert client.delete("/api/holidays/2026-12-25", headers=admin_h).status_code == 204


def test_audit_log_is_append_only(client, admin_h):
    with engine.connect() as conn:
        with pytest.raises(DBAPIError):
            conn.execute(text("UPDATE audit_log SET action='x'"))
        conn.rollback()
        with pytest.raises(DBAPIError):
            conn.execute(text("DELETE FROM audit_log"))
