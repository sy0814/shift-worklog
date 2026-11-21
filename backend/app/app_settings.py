"""后台可改的配置。"""

from sqlalchemy.orm import Session

from .models import AppSetting

DEFAULTS: dict = {
    # 未闭环警示：未完成且（从第一次录入起超过 N 小时 或 已移交 N 次及以上）
    "overdue_hours": 24,
    "overdue_handovers": 3,
}


def get_all(db: Session) -> dict:
    out = dict(DEFAULTS)
    for row in db.query(AppSetting).all():
        if row.key in DEFAULTS:
            out[row.key] = row.value
    return out


def get(db: Session, key: str):
    row = db.get(AppSetting, key)
    return row.value if row is not None else DEFAULTS[key]
