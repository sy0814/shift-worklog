"""首次启动时写入初始数据：默认车间、班次时间、内置角色、系统管理员账号。

班组、员工、班长账号由用户自己在网页上加（用户 2026-11-27：新装的系统不要内置班组和账号）。
示例数据（1～4 班、常白班，7 个班长账号，密码同用户名）只在 SEED_DEMO=true 时建：测试、开发、试用用。"""

import csv
from datetime import date, time, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit
from .config import get_settings
from . import worker_history
from .models import AppSetting, Department, Role, ShiftConfig, Team, User, Worker
from .permissions import ensure_builtin_roles
from .security import hash_password
from .shifts import CYCLE, WEEKDAYS

# 基准日 2026-11-01：3 班白1(0)、4 班中1(2)、1 班夜1(4)、2 班休1(6)
# 循环第 1 天 = 基准日往前推 offset 天
BASE_DATE = date(2026, 11, 1)
TEAMS = [
    # code, zh, sr, en, kind, offset（常白班为 None）
    ("T1", "1班", "Smena 1", "Team 1", "rotating", 4),
    ("T2", "2班", "Smena 2", "Team 2", "rotating", 6),
    ("T3", "3班", "Smena 3", "Team 3", "rotating", 0),
    ("T4", "4班", "Smena 4", "Team 4", "rotating", 2),
    ("DAY", "常白班", "Dnevna smena", "Day team", "day", None),
]


def team_cycle(kind: str, offset: int | None) -> dict:
    """初始班组的循环设置：倒班 8 天「白白中中夜夜休休」主班组；常白班 7 天「白×5 休休」从周一开始、节假日休息。"""
    if kind == "rotating":
        return dict(kind="cycle", pattern=list(CYCLE), cycle_start=BASE_DATE - timedelta(days=offset),
                    holiday_off=False, is_main=True)
    monday = BASE_DATE - timedelta(days=BASE_DATE.weekday())
    return dict(kind="cycle", pattern=list(WEEKDAYS), cycle_start=monday, holiday_off=True, is_main=False)


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


def ensure_default_department(db: Session) -> Department:
    """至少要有一个车间（迁移 0017 会建好；这里兜底）。"""
    d = db.scalar(select(Department).order_by(Department.sort_order, Department.id).limit(1))
    if d is None:
        d = Department(code="D1", name_zh="默认车间", name_sr="Podrazumevani pogon", name_en="Default workshop",
                       sort_order=0)
        db.add(d)
        db.flush()
    return d


def seed(db: Session) -> None:
    if db.get(ShiftConfig, 1) is not None:  # 已经初始化过（班次时间是第一次启动时建的）
        return
    s = get_settings()
    dept = ensure_default_department(db)
    db.add(ShiftConfig(id=1, day_start=time(7), middle_start=time(15), night_start=time(23)))
    db.add(User(username=s.admin_username, password_hash=hash_password(s.admin_password),
                full_name="管理员", role="admin", lang="zh"))
    ensure_builtin_roles(db)
    db.flush()
    if s.seed_demo:
        seed_demo(db, dept)
    audit.log(db, user_id=None, action="seed", entity="system", entity_id="init")
    db.commit()


def seed_demo(db: Session, dept: Department) -> None:
    """示例数据：1～4 班四班三倒 + 常白班，7 个班长（名册里同名的人 + 账号，密码同用户名）。"""
    teams: dict[str, Team] = {}
    for i, (code, zh, sr, en, kind, off) in enumerate(TEAMS):
        t = Team(code=code, name_zh=zh, name_sr=sr, name_en=en, sort_order=i, department_id=dept.id,
                 **team_cycle(kind, off))
        db.add(t)
        teams[code] = t
    db.flush()
    leader = db.scalar(select(Role).where(Role.code == "leader"))
    for username, code in LEADERS:
        # 班长也是名册里的人：先建名册记录（角色 = 班长），账号关联到它
        w = Worker(name=username, team_id=teams[code].id, role_id=leader.id)
        db.add(w)
        db.flush()
        worker_history.ensure_baseline(db, w, w.team_id)
        db.add(User(username=username, password_hash=hash_password(username), full_name=username, role="staff",
                    team_id=teams[code].id, worker_id=w.id, lang="zh"))
    db.flush()


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
