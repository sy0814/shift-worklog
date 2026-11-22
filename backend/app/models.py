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
    UniqueConstraint,
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
    # holiday：节假日（常白班休息）；workday：调休上班（周末常白班也上班）
    kind: Mapped[str] = mapped_column(String(10), default="holiday")


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


class Worker(Base):
    """员工名册（不开账号）。"""

    __tablename__ = "workers"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))
    employee_no: Mapped[str | None] = mapped_column(String(50), nullable=True, unique=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


TASK_STATUSES = ("not_started", "in_progress", "done", "handed_over", "discarded")


class Task(Base):
    __tablename__ = "tasks"

    id: Mapped[int] = mapped_column(primary_key=True)
    # 客户端生成的 UUID，离线草稿重复提交时用来去重
    client_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)

    # 三语内容。录入时只填原文语言那一列，其余由第 4 步的翻译补齐
    content_zh: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_sr: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_lang: Mapped[str] = mapped_column(String(5))
    # 遗留问题（同样三语）
    leftover_zh: Mapped[str | None] = mapped_column(Text, nullable=True)
    leftover_sr: Mapped[str | None] = mapped_column(Text, nullable=True)
    leftover_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    leftover_source_lang: Mapped[str | None] = mapped_column(String(5), nullable=True)
    # pending（待翻译）/ done / failed（后台多次重试仍失败，等管理员手动重试）
    translation_status: Mapped[str] = mapped_column(String(10), default="pending", index=True)
    translation_attempts: Mapped[int] = mapped_column(Integer, default=0)
    translation_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # 人工校对过的译文列，如 ["content_sr", "leftover_en"]
    manual_fields: Mapped[list] = mapped_column(JSON, default=list)

    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)  # 当前所属班组
    origin_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))  # 创建班组
    source_task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)

    status: Mapped[str] = mapped_column(String(15), default="not_started", index=True)
    # 录入所在的班次（按 recorded_at 推算；夜班归属开始那天）
    shift_date: Mapped[date] = mapped_column(Date, index=True)
    shift_kind: Mapped[str] = mapped_column(String(10))
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 移交链：第一次录入的时间、已经移交过几次（用于未闭环警示）
    chain_started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    handover_count: Mapped[int] = mapped_column(Integer, default=0)

    # 废弃原因（三语）
    discard_reason_zh: Mapped[str | None] = mapped_column(Text, nullable=True)
    discard_reason_sr: Mapped[str | None] = mapped_column(Text, nullable=True)
    discard_reason_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    discard_reason_lang: Mapped[str | None] = mapped_column(String(5), nullable=True)
    discarded_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    discarded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # 录入时间（离线草稿为本地保存时间）
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    workers: Mapped[list[Worker]] = relationship(secondary="task_workers", order_by="Worker.id")
    attachments: Mapped[list["Attachment"]] = relationship(
        primaryjoin="and_(Attachment.task_id == Task.id, Attachment.deleted_at.is_(None))",
        order_by="Attachment.taken_at", viewonly=True)


class TaskWorker(Base):
    __tablename__ = "task_workers"

    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"), primary_key=True)


class Attachment(Base):
    """任务图片。原图 + 浏览图 + 缩略图，软删除。"""

    __tablename__ = "attachments"

    id: Mapped[int] = mapped_column(primary_key=True)
    client_id: Mapped[str] = mapped_column(String(36), unique=True, index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    filename: Mapped[str] = mapped_column(String(255))
    content_type: Mapped[str] = mapped_column(String(50))
    size: Mapped[int] = mapped_column(Integer)
    width: Mapped[int] = mapped_column(Integer)
    height: Mapped[int] = mapped_column(Integer)
    path_original: Mapped[str] = mapped_column(String(255))
    path_view: Mapped[str] = mapped_column(String(255))
    path_thumb: Mapped[str] = mapped_column(String(255))
    taken_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    taken_at_source: Mapped[str] = mapped_column(String(10))  # exif / file / upload
    uploaded_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    deleted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


class TaskHandover(Base):
    """移交记录：原任务标记为已移交，在接收班组生成一条新任务（source_task_id 指回原任务）。"""

    __tablename__ = "task_handovers"

    id: Mapped[int] = mapped_column(primary_key=True)
    from_task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), unique=True)
    to_task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), unique=True)
    from_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"))
    to_team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    default_team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)  # 系统建议的接班班组
    note: Mapped[str | None] = mapped_column(Text, nullable=True)  # 交接说明（原文，会作为新任务的遗留问题）
    note_lang: Mapped[str | None] = mapped_column(String(5), nullable=True)
    by_user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AppSetting(Base):
    """可在后台修改的配置（key → JSON 值）。"""

    __tablename__ = "app_settings"

    key: Mapped[str] = mapped_column(String(50), primary_key=True)
    value: Mapped[dict | list | int | str | None] = mapped_column(JSON)


class GlossaryTerm(Base):
    """术语表：翻译时拼进系统提示词。"""

    __tablename__ = "glossary"

    id: Mapped[int] = mapped_column(primary_key=True)
    zh: Mapped[str] = mapped_column(String(200))
    sr: Mapped[str] = mapped_column(String(200))
    en: Mapped[str] = mapped_column(String(200))
    category: Mapped[str] = mapped_column(String(50), default="")
    note: Mapped[str] = mapped_column(String(200), default="")
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


ATTENDANCE_STATUSES = ("present", "leave", "sick", "absent", "off")


class Attendance(Base):
    """出勤例外记录。默认出勤按排班推算、不存库；这里只存导入或手工改过的。"""

    __tablename__ = "attendance"
    __table_args__ = (UniqueConstraint("worker_id", "day", name="uq_attendance_worker_day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)  # 班次日期（夜班归属开始那天）
    # present 出勤 / leave 请假 / sick 病假 / absent 缺勤 / off 休息
    status: Mapped[str] = mapped_column(String(10))
    # 实际上的班次（调班、加班时与本班组排班不同）；为空表示按本班组排班
    shift_kind: Mapped[str | None] = mapped_column(String(10), nullable=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)  # 顶哪个班组的班
    note: Mapped[str] = mapped_column(String(200), default="")
    source: Mapped[str] = mapped_column(String(10))  # import / manual
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
