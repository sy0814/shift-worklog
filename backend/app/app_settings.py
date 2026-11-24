"""后台可改的配置。"""

from sqlalchemy.orm import Session

from .models import AppSetting

DEFAULTS: dict = {
    # 未闭环警示：未完成且（从第一次录入起超过 N 小时 或 已移交 N 次及以上）
    "overdue_hours": 24,
    "overdue_handovers": 3,
}
# 新员工默认密码（不在 DEFAULTS 里，避免通过 GET /api/settings 给所有人看到；只有管理员能读写）
DEFAULT_PASSWORD_KEY = "default_password"
DEFAULT_PASSWORD = "123456"


def default_password(db: Session) -> str:
    row = db.get(AppSetting, DEFAULT_PASSWORD_KEY)
    return row.value if row is not None and isinstance(row.value, str) and row.value else DEFAULT_PASSWORD


def get_all(db: Session) -> dict:
    out = dict(DEFAULTS)
    for row in db.query(AppSetting).all():
        if row.key in DEFAULTS:
            out[row.key] = row.value
    return out


def get(db: Session, key: str):
    row = db.get(AppSetting, key)
    return row.value if row is not None else DEFAULTS[key]
