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
    false,
    true,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Department(Base):
    """车间（部门）：班组之上的一层。排班的主班组、合并显示、交接顺序、排班检查都只在同一个车间里算；
    「本车间」权限范围（dept）也按它。跨车间可以移交任务、借调人员。只有一个车间时，界面上不显示车间。"""

    __tablename__ = "departments"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # D1, D2 ……
    name_zh: Mapped[str] = mapped_column(String(100))
    name_sr: Mapped[str] = mapped_column(String(100))
    name_en: Mapped[str] = mapped_column(String(100))
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())  # 停用后不在导航页显示
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[int] = mapped_column(primary_key=True)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), index=True)  # 属于哪个车间
    code: Mapped[str] = mapped_column(String(20), unique=True)  # T1..T4, DAY
    name_zh: Mapped[str] = mapped_column(String(50))
    name_sr: Mapped[str] = mapped_column(String(50))
    name_en: Mapped[str] = mapped_column(String(50))
    kind: Mapped[str] = mapped_column(String(10))  # cycle（按循环排班）/ manual（不固定，只按调班）
    # 循环：每天上什么（day / middle / night / off），循环第 1 天，节假日是否休息（见 shifts.Cycle）
    pattern: Mapped[list | None] = mapped_column(JSON, nullable=True)
    cycle_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    holiday_off: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    # 主班组：首页卡片、交接班单独显示；其他班组合并到同一班次的主班组里
    is_main: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    # 临时班组的有效期（含首尾）；空 = 长期。范围以外这个班组一律休息
    active_from: Mapped[date | None] = mapped_column(Date, nullable=True)
    active_to: Mapped[date | None] = mapped_column(Date, nullable=True)


class Role(Base):
    """角色（班长、副班长、成员……）：能做什么（权限表）、怎么登录、首页是否单独显示。管理员在「角色权限」页维护。"""

    __tablename__ = "roles"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(20), unique=True)  # leader / deputy / member / r<n>
    name_zh: Mapped[str] = mapped_column(String(50))
    name_sr: Mapped[str] = mapped_column(String(50))
    name_en: Mapped[str] = mapped_column(String(50))
    # {权限: 范围}，范围 none / self / team / all，见 permissions.PERMS
    permissions: Mapped[dict] = mapped_column(JSON, default=dict)
    login_mode: Mapped[str] = mapped_column(String(10), default="pin")  # password（个人账号）/ pin（班组公共账号 + 个人密码）
    show_on_top: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())  # 首页人员状态里单独列在上面
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
    is_builtin: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())


class User(Base):
    """登录账号。管理员是系统账号（不在名册里）；其他账号都关联名册里的一个人（worker_id），
    姓名、班组、角色以名册为准（full_name、team_id 跟着名册同步，方便查询）。"""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(50), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(100))  # 个人账号的密码，或班组公共账号里这个人的个人密码
    full_name: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(10))  # admin（系统管理员）/ staff（名册里的人，权限看角色）
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    worker_id: Mapped[int | None] = mapped_column(ForeignKey("workers.id"), nullable=True, unique=True)
    lang: Mapped[str] = mapped_column(String(5), default="zh")  # zh / sr / en
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    failed_logins: Mapped[int] = mapped_column(Integer, default=0, server_default="0")
    locked_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    # 用的是默认密码或别人重设的密码：登录后必须先改密码才能用系统
    must_change_password: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())

    team: Mapped[Team | None] = relationship()


class ShiftConfig(Base):
    """排班配置，只有一行（id=1）。"""

    __tablename__ = "shift_config"

    id: Mapped[int] = mapped_column(primary_key=True)
    day_start: Mapped[time] = mapped_column(Time)
    middle_start: Mapped[time] = mapped_column(Time)
    night_start: Mapped[time] = mapped_column(Time)


class Holiday(Base):
    __tablename__ = "holidays"

    day: Mapped[date] = mapped_column(Date, primary_key=True)
    name: Mapped[str] = mapped_column(String(100), default="")
    # holiday：节假日（常白班休息）；workday：调休上班（周末常白班也上班）
    kind: Mapped[str] = mapped_column(String(10), default="holiday")


class TeamShiftOverride(Base):
    """班组整体调班：某个班组某一天改上别的班（或休息），覆盖排班推算。"""

    __tablename__ = "team_shift_overrides"
    __table_args__ = (UniqueConstraint("team_id", "day"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)
    day: Mapped[date] = mapped_column(Date, index=True)  # 班次日（夜班归属下班的那天）
    shift_kind: Mapped[str] = mapped_column(String(10))  # day / middle / night / off（有 hours 时 = 它算作的班）
    hours: Mapped[str | None] = mapped_column(String(60), nullable=True)  # 自定义时间段，例 07:00-12:00,14:00-17:00
    note: Mapped[str] = mapped_column(String(200), default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Overtime(Base):
    """加班：某人（worker_id）或整个班组（team_id，当天在这个班上班的人都算）某个班次加班到 until。"""

    __tablename__ = "overtime"

    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, index=True)  # 班次日
    shift_kind: Mapped[str] = mapped_column(String(10))  # 在哪个班次后面加班
    worker_id: Mapped[int | None] = mapped_column(ForeignKey("workers.id"), nullable=True, index=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    until: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # 加班到几点
    note: Mapped[str] = mapped_column(String(200), default="")
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


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
    avatar_path: Mapped[str | None] = mapped_column(String(255), nullable=True)  # 头像（上传目录下的相对路径）
    extra: Mapped[dict] = mapped_column(JSON, default=dict, server_default="{}")  # 自定义列的值 {列 id: 文字}
    role_id: Mapped[int | None] = mapped_column(ForeignKey("roles.id"), nullable=True)  # 空 = 成员
    # 属于哪个车间。有班组时自动等于班组的车间（departments.py 里 before_flush 同步）；
    # 没有班组的人（例如车间管理员）单独设
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True, index=True)


class Project(Base):
    """项目：下面有多个子项目（子项目就是普通任务，tasks.project_id 指向这里）。
    所有子项目都完成（或废弃）才算完成。可移交的项目，子项目本班没做完会在下班后自动移交给下一个班组。"""

    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(primary_key=True)
    name_zh: Mapped[str | None] = mapped_column(Text, nullable=True)
    name_sr: Mapped[str | None] = mapped_column(Text, nullable=True)
    name_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_lang: Mapped[str] = mapped_column(String(5))
    translation_status: Mapped[str] = mapped_column(String(10), default="pending")
    transferable: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    team_id: Mapped[int] = mapped_column(ForeignKey("teams.id"), index=True)  # 建项目的班组（班长按它判断能不能管）
    deadline: Mapped[date | None] = mapped_column(Date, nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    closed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 全部子项目结束的时间
    inspection_id: Mapped[int | None] = mapped_column(ForeignKey("inspection_templates.id"), nullable=True, index=True)


class Equipment(Base):
    """设备台账：设备编号、名称、区域、型号、备注。名称 / 区域 / 备注三语，只填一种时后台自动翻译补齐。
    任务可以关联到设备（tasks.equipment_id），设备页能看到它的所有任务。"""

    __tablename__ = "equipment"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(60), unique=True)  # 设备编号（唯一）
    name_zh: Mapped[str | None] = mapped_column(String(200), nullable=True)
    name_sr: Mapped[str | None] = mapped_column(String(200), nullable=True)
    name_en: Mapped[str | None] = mapped_column(String(200), nullable=True)
    area_zh: Mapped[str | None] = mapped_column(String(200), nullable=True)
    area_sr: Mapped[str | None] = mapped_column(String(200), nullable=True)
    area_en: Mapped[str | None] = mapped_column(String(200), nullable=True)
    note_zh: Mapped[str | None] = mapped_column(Text, nullable=True)
    note_sr: Mapped[str | None] = mapped_column(Text, nullable=True)
    note_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(String(200), default="", server_default="")  # 型号规格（不翻译）
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True, index=True)  # 空 = 全厂共用
    source_lang: Mapped[str] = mapped_column(String(5))  # 录入时的语言（翻译从这个语言出发）
    translation_status: Mapped[str] = mapped_column(String(10), default="pending")
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorkerSchedule(Base):
    """员工的班组 / 排班变更记录：从 effective_from 这天起，属于哪个班组、跟班组排班还是按个人循环。
    出勤、工时按当天有效的那条算，所以换班组后以前的出勤不变。"""

    __tablename__ = "worker_schedules"
    __table_args__ = (UniqueConstraint("worker_id", "effective_from"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"), index=True)
    effective_from: Mapped[date] = mapped_column(Date)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    pattern: Mapped[list | None] = mapped_column(JSON, nullable=True)  # 空 = 跟班组排班
    cycle_start: Mapped[date | None] = mapped_column(Date, nullable=True)
    holiday_off: Mapped[bool] = mapped_column(Boolean, default=False, server_default=false())
    note: Mapped[str] = mapped_column(String(200), default="", server_default="")
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class WorkerField(Base):
    """员工名册的自定义列（管理员在网页上加，或导入 Excel 时自动加）。"""

    __tablename__ = "worker_fields"

    id: Mapped[int] = mapped_column(primary_key=True)
    label: Mapped[str] = mapped_column(String(50), unique=True)  # 列名（按录入的原样显示）
    sort_order: Mapped[int] = mapped_column(Integer, default=0)
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
    inspection_id: Mapped[int | None] = mapped_column(ForeignKey("inspection_templates.id"), nullable=True, index=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True, index=True)  # 属于哪个项目（子项目）
    equipment_id: Mapped[int | None] = mapped_column(ForeignKey("equipment.id"), nullable=True, index=True)  # 关联的设备
    # 可移交：False = 这条任务一直留在本班组（不能手动移交、不参加自动移交）。项目子项目还要看项目的设置
    transferable: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())
    # 带队人员（一个，可不填）。带队人同时也在 workers（task_workers）里，所以按「参与」统计时自动算上他
    lead_worker_id: Mapped[int | None] = mapped_column(ForeignKey("workers.id"), nullable=True, index=True)

    status: Mapped[str] = mapped_column(String(15), default="not_started", index=True)
    # 录入所在的班次（按 recorded_at 推算；夜班归属下班那天）
    shift_date: Mapped[date] = mapped_column(Date, index=True)
    shift_kind: Mapped[str] = mapped_column(String(10))
    start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    confirmed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # 任务类型（设备统计用）：fault 故障维修 / maintenance 计划检修 / inspection 巡查 / other 其他
    kind: Mapped[str] = mapped_column(String(12), default="other", server_default="other")

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

    # 全部参与人（含带队人）；带队人另见 lead
    workers: Mapped[list[Worker]] = relationship(secondary="task_workers", order_by="Worker.id")
    lead: Mapped[Worker | None] = relationship(foreign_keys=[lead_worker_id], viewonly=True)
    project: Mapped["Project | None"] = relationship(foreign_keys=[project_id], viewonly=True)
    attachments: Mapped[list["Attachment"]] = relationship(
        primaryjoin="and_(Attachment.task_id == Task.id, Attachment.deleted_at.is_(None))",
        order_by="Attachment.taken_at", viewonly=True)


class TaskWorker(Base):
    __tablename__ = "task_workers"

    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id", ondelete="CASCADE"), primary_key=True)
    worker_id: Mapped[int] = mapped_column(ForeignKey("workers.id"), primary_key=True)


class TaskLog(Base):
    """任务的班次日志：任何时候都可以加一条自由填写的记录，自动翻译成另外两种语言。
    属于哪个班次按录入时间算（离线写的按写的时间，不按同步时间）。任务移交后，下一班能看到整条移交链上的日志。"""

    __tablename__ = "task_logs"

    id: Mapped[int] = mapped_column(primary_key=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("tasks.id"), index=True)
    client_id: Mapped[str | None] = mapped_column(String(36), unique=True, nullable=True)  # 离线发件箱去重
    content_zh: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_sr: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_en: Mapped[str | None] = mapped_column(Text, nullable=True)
    source_lang: Mapped[str] = mapped_column(String(5))
    translation_status: Mapped[str] = mapped_column(String(10), default="pending")  # pending / done
    shift_date: Mapped[date] = mapped_column(Date)  # 写的时候是哪个班次（夜班归属下班那天）
    shift_kind: Mapped[str] = mapped_column(String(10))
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)  # 写的时候任务属于哪个班组
    worker_id: Mapped[int | None] = mapped_column(ForeignKey("workers.id"), nullable=True)  # 写的人（名册）
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    recorded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # 写的时间
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 软删除
    deleted_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)


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
    archived_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 原图搬到归档盘的时间


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
    day: Mapped[date] = mapped_column(Date, index=True)  # 班次日期（夜班归属下班那天）
    # present 出勤 / leave 请假 / sick 病假 / absent 缺勤 / off 休息
    status: Mapped[str] = mapped_column(String(10))
    # 实际上的班次（调班、加班时与本班组排班不同）；为空表示按本班组排班
    shift_kind: Mapped[str | None] = mapped_column(String(10), nullable=True)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)  # 顶哪个班组的班
    note: Mapped[str] = mapped_column(String(200), default="")
    # 工厂出勤月表里的原始写法（AL、SL、BT……），出勤页原样显示；手工改的没有
    code: Mapped[str | None] = mapped_column(String(10), nullable=True)
    source: Mapped[str] = mapped_column(String(10))  # import / manual
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class AiReport(Base):
    """AI 工作量分析报告。统计数据由程序算好（stats），模型只负责据此写报告（report_md）。"""

    __tablename__ = "ai_reports"

    id: Mapped[int] = mapped_column(primary_key=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, index=True)
    start: Mapped[date] = mapped_column(Date)
    end: Mapped[date] = mapped_column(Date)
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    department_id: Mapped[int | None] = mapped_column(ForeignKey("departments.id"), nullable=True)  # 不选班组时：分析哪个车间
    lang: Mapped[str] = mapped_column(String(5))
    status: Mapped[str] = mapped_column(String(10), default="pending")  # pending / running / done / failed
    model: Mapped[str] = mapped_column(String(100), default="")
    stats: Mapped[dict | None] = mapped_column(JSON, nullable=True)
    report_md: Mapped[str | None] = mapped_column(Text, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    usage: Mapped[dict | None] = mapped_column(JSON, nullable=True)  # token 用量
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class InspectionTemplate(Base):
    """定期巡查项：按周期自动生成任务。规则说明见 app/inspection_schedule.py。"""

    __tablename__ = "inspection_templates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(100))  # 列表里显示的简称
    content: Mapped[str] = mapped_column(Text)  # 生成任务的工作内容（原文）
    lang: Mapped[str] = mapped_column(String(5))
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    kind: Mapped[str] = mapped_column(String(10))  # daily / weekly / monthly / yearly / shift
    at_time: Mapped[time] = mapped_column(Time, default=time(8, 0))
    every_n: Mapped[int] = mapped_column(Integer, default=1)
    weekdays: Mapped[list] = mapped_column(JSON, default=list)
    month_days: Mapped[list] = mapped_column(JSON, default=list)
    year_dates: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")  # 每年："MM-DD"
    shift_kinds: Mapped[list] = mapped_column(JSON, default=list)
    start_date: Mapped[date] = mapped_column(Date)
    department_id: Mapped[int] = mapped_column(ForeignKey("departments.id"), index=True)  # 「派给在班班组」按这个车间找
    assign: Mapped[str] = mapped_column(String(10), default="on_duty")  # on_duty / fixed
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    worker_ids: Mapped[list] = mapped_column(JSON, default=list)  # 只在固定班组时使用
    # 小项目：[{content, team_id?, worker_id?}]。有小项目时，每次派发生成一个「项目」（名称 = 巡查项名称），
    # 每个小项目是一个子项目：分给指定的人 / 班组，没指定就给这次派给的班组
    sub_items: Mapped[list] = mapped_column(JSON, default=list, server_default="[]")
    transferable: Mapped[bool] = mapped_column(Boolean, default=True, server_default=true())  # 生成的项目是否可移交
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True, index=True)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class InspectionRun(Base):
    """每次派发的记录。(template_id, occurrence_at) 唯一，保证同一次不会派两遍。"""

    __tablename__ = "inspection_runs"
    __table_args__ = (UniqueConstraint("template_id", "occurrence_at", name="uq_inspection_runs_occurrence"),)

    id: Mapped[int] = mapped_column(primary_key=True)
    template_id: Mapped[int] = mapped_column(ForeignKey("inspection_templates.id"), index=True)
    occurrence_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))  # 应触发的时间
    task_id: Mapped[int | None] = mapped_column(ForeignKey("tasks.id"), nullable=True)
    project_id: Mapped[int | None] = mapped_column(ForeignKey("projects.id"), nullable=True)  # 有小项目时生成的项目
    team_id: Mapped[int | None] = mapped_column(ForeignKey("teams.id"), nullable=True)
    status: Mapped[str] = mapped_column(String(10))  # created / skipped（补派时跳过的旧次数）/ manual / failed
    note: Mapped[str] = mapped_column(String(300), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
