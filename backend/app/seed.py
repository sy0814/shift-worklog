"""首次启动时写入初始数据：5 个班组、排班基准、管理员和班长账号。"""

import csv
from datetime import date, time
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit
from .config import get_settings
from .models import AppSetting, ShiftConfig, Team, User
from .security import hash_password

# 基准日 2026-11-01：3 班白1(0)、4 班中1(2)、1 班夜1(4)、2 班休1(6)
TEAMS = [
    # code, zh, sr, en, kind, offset
    ("T1", "1班", "Smena 1", "Team 1", "rotating", 4),
    ("T2", "2班", "Smena 2", "Team 2", "rotating", 6),
    ("T3", "3班", "Smena 3", "Team 3", "rotating", 0),
    ("T4", "4班", "Smena 4", "Team 4", "rotating", 2),
    ("DAY", "常白班", "Dnevna smena", "Day team", "day", None),
]

# 初始班长账号：倒班每班 1 个，常白班 3 个。初始密码 = 用户名，首次登录后请修改。
LEADERS = [
    ("t1_leader1", "T1"),
    ("t2_leader1", "T2"),
    ("t3_leader1", "T3"),
    ("t4_leader1", "T4"),
    ("day_leader1", "DAY"),
    ("day_leader2", "DAY"),
    ("day_leader3", "DAY"),
]


def seed(db: Session) -> None:
    if db.scalar(select(Team).limit(1)) is not None:
        return
    s = get_settings()
    teams: dict[str, Team] = {}
    for i, (code, zh, sr, en, kind, off) in enumerate(TEAMS):
        t = Team(code=code, name_zh=zh, name_sr=sr, name_en=en, kind=kind,
                 cycle_offset=off, sort_order=i)
        db.add(t)
        teams[code] = t
    db.add(ShiftConfig(id=1, base_date=date(2026, 11, 1),
                       day_start=time(7), middle_start=time(15), night_start=time(23)))
    db.flush()

    db.add(User(username=s.admin_username, password_hash=hash_password(s.admin_password),
                full_name="管理员", role="admin", lang="zh"))
    for username, code in LEADERS:
        db.add(User(username=username, password_hash=hash_password(username),
                    full_name=username, role="leader", team_id=teams[code].id, lang="zh"))
    db.flush()
    audit.log(db, user_id=None, action="seed", entity="system", entity_id="init")
    db.commit()


GLOSSARY_SEED = Path(__file__).with_name("glossary_seed.csv")


def seed_glossary(db: Session) -> None:
    """首次启动导入术语表初始数据（只导一次；之后由管理员在后台维护）。"""
    if db.get(AppSetting, "glossary_seeded") is not None or not GLOSSARY_SEED.exists():
        return
    from .routers.translation import import_rows

    with GLOSSARY_SEED.open(encoding="utf-8-sig") as f:
        import_rows(db, list(csv.DictReader(f)), None)
    db.add(AppSetting(key="glossary_seeded", value=True))
    db.commit()
