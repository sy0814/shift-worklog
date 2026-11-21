"""数据模型（第 1 步：账号、班组、排班配置、节假日、留痕）。

任务、参与人员、移交、出勤、术语表等在后续步骤加入。
"""

from datetime import date, datetime, time, timezone

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    Time,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # T1..T4, DAY
    name_zh: Mapped[str] = mapped_column(String(50))
    name_sr: Mapped[str] = mapped_column(String(50))
    name_en: Mapped[str] = mapped_column(String(50))
    kind: Mapped[str] = mapped_column(String(10))  # rotating（倒班）/ day（常白班）
    # 倒班班组在基准日处于 8 天循环中的位置 0..7；常白班为空
    cycle_offset: Mapped[int | None] = mapped_column(Integer, nullable=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    full_name: Mapped[str] = mapped_column(String(100))
    # admin（管理员）/ leader（班长）；以后如给员工开账号，加 member
    role: Mapped[str] = mapped_column(String(10))
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    lang: Mapped[str] = mapped_column(String(5), default="zh")  # zh / sr / en
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    team: Mapped[Team | None] = relationship()


class ShiftConfig(Base):
    """排班配置，只有一行（id=1）。"""

    __tablename__ = "shift_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    base_date: Mapped[date] = mapped_column(Date)
    day_start: Mapped[time] = mapped_column(Time)
    middle_start: Mapped[time] = mapped_column(Time)
    night_start: Mapped[time] = mapped_column(Time)


class Holiday(Base):
    __tablename__ = "holidays"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), default="")


class AuditLog(Base):
    """只能追加的操作留痕。数据库层用触发器禁止 UPDATE / DELETE（见 audit.py）。"""

    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(30))  # create / update / delete / login / ...
    entity: Mapped[str] = mapped_column(String(30), index=True)
    entity_id: Mapped[str] = mapped_column(String(50), index=True)
    field: Mapped[str | None] = mapped_column(String(50), nullable=True)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSON, nullable=True)
