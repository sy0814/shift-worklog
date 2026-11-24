from datetime import date, datetime, time, timezone
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field, model_validator


def _utc(d: datetime) -> datetime:
    # SQLite 读回来的是 naive 时间，库里统一存 UTC
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d


UTCDateTime = Annotated[datetime, AfterValidator(_utc)]

Lang = Literal["zh", "sr", "en"]
Role = Literal["admin", "staff"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TeamOut(ORM):
    id: int
    code: str
    name_zh: str
    name_sr: str
    name_en: str
    kind: str  # cycle / manual
    pattern: list[str] | None = None
    cycle_start: date | None = None
    holiday_off: bool = False
    is_main: bool = False
    sort_order: int = 0
    active_from: date | None = None
    active_to: date | None = None


class UserOut(ORM):
    id: int
    username: str
    full_name: str
    role: str
    team_id: int | None
    lang: str
    is_active: bool
    created_at: UTCDateTime
    worker_id: int | None = None
    must_change_password: bool = False
    last_login_at: UTCDateTime | None = None
    locked_until: UTCDateTime | None = None


class RoleBrief(BaseModel):
    id: int
    code: str
    name_zh: str
    name_sr: str
    name_en: str
    login_mode: str
    show_on_top: bool


class MeOut(UserOut):
    """当前用户：账号 + 角色 + 权限表（{权限: 范围}；管理员为全部 all）+ 本班组和合并显示的班组。"""
    role_info: RoleBrief | None = None
    perms: dict[str, str] = {}
    group_team_ids: list[int] = []


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: MeOut


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=50, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=6, max_length=100)
    full_name: str = Field(min_length=1, max_length=100)
    role: Literal["admin"] = "admin"  # 这里只建系统管理员账号；名册里的人的账号在「员工名册」里开
    lang: Lang = "zh"


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=100)
    lang: Lang | None = None
    is_active: bool | None = None


class PasswordReset(BaseModel):
    password: str = Field(min_length=6, max_length=100)


class PasswordChange(BaseModel):
    old_password: str
    new_password: str = Field(min_length=4, max_length=100)  # 个人账号至少 6 位（接口里再查）；班组账号的个人密码至少 4 位


class MeUpdate(BaseModel):
    lang: Lang | None = None
    full_name: str | None = Field(default=None, min_length=1, max_length=100)


class ShiftConfigOut(ORM):
    """班次时间（各班组的循环在「班组管理」里各自设置）。"""
    day_start: time
    middle_start: time
    night_start: time


class ShiftConfigIn(BaseModel):
    day_start: time
    middle_start: time
    night_start: time


class HolidayIO(ORM):
    day: date
    name: str = ""
    kind: Literal["holiday", "workday"] = "holiday"


class ShiftSlot(BaseModel):
    shift_date: date
    kind: str
    start: datetime
    end: datetime
    team_ids: list[int]


class ShiftNow(BaseModel):
    now: datetime
    current: ShiftSlot
    next: ShiftSlot


class CalendarDay(BaseModel):
    day: date
    workday: bool
    shifts: dict[int, str]  # team_id -> day/middle/night/off
    changed: dict[int, str] = {}  # 整体调班的班组：team_id -> 原本的班次
    hours: dict[int, str] = {}  # 自定义上班时间的班组：team_id -> "07:00-12:00,14:00-17:00"（shifts 里是它算作的班）


class AuditOut(ORM):
    id: int
    at: UTCDateTime
    user_id: int | None
    action: str
    entity: str
    entity_id: str
    field: str | None
    old_value: str | None
    new_value: str | None


# ---------------- 员工名册 ----------------
class WorkerOut(ORM):
    id: int
    name: str
    employee_no: str | None
    team_id: int | None
    is_active: bool
    avatar_url: str | None = None  # 没有头像时为空，前端显示名字
    extra: dict[str, str] = {}  # 自定义列 {列 id: 值}
    role_id: int | None = None  # 空 = 成员

    @model_validator(mode="before")
    @classmethod
    def _from_orm_with_avatar(cls, v):
        if hasattr(v, "avatar_path"):  # 数据库对象：头像路径 → 带签名的地址
            from .security import avatar_url

            return {"id": v.id, "name": v.name, "employee_no": v.employee_no, "team_id": v.team_id,
                    "is_active": v.is_active, "extra": {str(k): str(x) for k, x in (v.extra or {}).items()},
                    "role_id": v.role_id,
                    "avatar_url": avatar_url(v.id, v.avatar_path) if v.avatar_path else None}
        return v


class WorkerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    employee_no: str | None = Field(default=None, max_length=50)
    team_id: int | None = None
    extra: dict[str, str] = {}


class WorkerBulkCreate(BaseModel):
    names: list[str] = Field(min_length=1, max_length=500)
    team_id: int | None = None


class WorkerUpdate(BaseModel):
    role_id: int | None = None  # 角色（只有管理员能改）
    name: str | None = Field(default=None, min_length=1, max_length=100)
    employee_no: str | None = Field(default=None, max_length=50)
    team_id: int | None = None
    is_active: bool | None = None
    extra: dict[str, str] | None = None  # 只改给出的列；值为空字符串 = 清空


# ---------------- 任务 ----------------
TaskStatus = Literal["not_started", "in_progress", "done", "handed_over", "discarded"]
UUIDStr = Annotated[str, Field(pattern=r"^[0-9a-fA-F-]{36}$")]


class Trilingual(BaseModel):
    zh: str | None = None
    sr: str | None = None
    en: str | None = None


class TaskCreate(BaseModel):
    client_id: UUIDStr
    content: str = Field(min_length=1, max_length=5000)
    lang: Lang
    team_id: int | None = None  # 班长忽略此字段，固定为本班组；管理员必填
    worker_ids: list[int] = Field(default_factory=list, max_length=200)
    lead_worker_id: int | None = None  # 带队人员（可不填）
    equipment_id: int | None = None  # 关联的设备（可不填）
    status: Literal["not_started", "in_progress", "done"] = "not_started"
    start_at: datetime | None = None
    end_at: datetime | None = None
    leftover: str | None = Field(default=None, max_length=5000)
    recorded_at: datetime | None = None  # 离线草稿的本地保存时间


class TaskUpdate(BaseModel):
    content: str | None = Field(default=None, min_length=1, max_length=5000)
    leftover: str | None = Field(default=None, max_length=5000)
    lang: Lang | None = None  # 修改后的内容文字是哪种语言（默认用户界面语言）
    leftover_lang: Lang | None = None  # 遗留问题文字的语言（默认同 lang）
    worker_ids: list[int] | None = Field(default=None, max_length=200)
    lead_worker_id: int | None = None  # 传了就改（null = 去掉带队人），不传不改
    equipment_id: int | None = None  # 传了就改（null = 不关联设备），不传不改
    start_at: datetime | None = None
    end_at: datetime | None = None
    # 原文改了以后：True 重新翻译（覆盖人工校对的译文）；False 保留现有译文
    retranslate: bool = True


class HandoverRequest(BaseModel):
    task_ids: list[int] = Field(min_length=1, max_length=200)
    to_team_id: int | None = None  # 不填则用系统建议的接班班组
    note: str | None = Field(default=None, max_length=5000)
    lang: Lang | None = None


class DiscardRequest(BaseModel):
    reason: str = Field(min_length=1, max_length=5000)
    lang: Lang | None = None


class HandoverDefault(BaseModel):
    team_id: int
    to_team_id: int | None


class HandoverInfo(BaseModel):
    team_id: int  # 对方班组（移入：来自哪个班组；移出：交给哪个班组）
    task_id: int  # 对方任务
    default_team_id: int | None
    note: str | None
    note_lang: str | None
    by_name: str
    at: UTCDateTime


class SettingsIO(BaseModel):
    overdue_hours: int = Field(ge=1, le=24 * 60)
    overdue_handovers: int = Field(ge=1, le=100)


class TaskStatusChange(BaseModel):
    status: Literal["not_started", "in_progress", "done"]
    # 离线时点的：expect = 点的时候看到的状态（服务器上已经变了就拒绝，不覆盖别人的操作）；
    # at = 实际点的时间（开始 / 完成时间按它记，最多往前 3 天）
    expect: Literal["not_started", "in_progress", "done"] | None = None
    at: datetime | None = None


class AttachmentOut(BaseModel):
    id: int
    client_id: str
    filename: str
    width: int
    height: int
    taken_at: UTCDateTime
    taken_at_source: str
    uploaded_by: int
    uploaded_by_name: str
    uploaded_at: UTCDateTime
    url_thumb: str
    url_view: str
    url_original: str
    can_delete: bool = False


class ProjectBrief(BaseModel):
    id: int
    name: Trilingual
    source_lang: str
    transferable: bool
    done: int
    total: int


class EquipmentBrief(BaseModel):
    id: int
    code: str
    name: Trilingual
    source_lang: str


class TaskOut(BaseModel):
    id: int
    client_id: str
    content: Trilingual
    source_lang: str
    leftover: Trilingual
    leftover_source_lang: str | None
    translation_status: str
    translation_error: str | None
    manual_fields: list[str]
    team_id: int
    origin_team_id: int
    source_task_id: int | None
    inspection_id: int | None = None
    inspection_name: str | None = None
    status: str
    shift_date: date
    shift_kind: str
    start_at: UTCDateTime | None
    end_at: UTCDateTime | None
    confirmed_by: int | None
    confirmed_by_name: str | None
    confirmed_at: UTCDateTime | None
    created_by: int
    created_by_name: str
    updated_by: int
    updated_by_name: str
    recorded_at: UTCDateTime
    created_at: UTCDateTime
    updated_at: UTCDateTime
    lead: WorkerOut | None = None  # 带队人员
    workers: list[WorkerOut]  # 参与人员（不含带队人）
    attachments: list[AttachmentOut]
    can_edit: bool  # = perms.edit
    can_correct: bool = False  # 能否校对译文
    # 当前用户对这条任务能做什么：edit / status（开始、完成）/ handover / discard / photo（传照片）/ correct（校对译文）
    perms: dict[str, bool] = {}
    project: "ProjectBrief | None" = None  # 属于哪个项目（子项目）
    equipment: EquipmentBrief | None = None  # 关联的设备
    # 移交 / 废弃 / 警示
    chain_started_at: UTCDateTime
    handover_count: int
    age_hours: float
    overdue: bool
    handover_in: HandoverInfo | None
    handover_out: HandoverInfo | None
    discard_reason: Trilingual
    discard_reason_lang: str | None
    discarded_by_name: str | None
    discarded_at: UTCDateTime | None


class TaskPage(BaseModel):
    items: list[TaskOut]
    total: int


class HistoryOut(AuditOut):
    user_name: str | None


class BoardOut(BaseModel):
    team_id: int  # 主班组（合并时是倒班班组）
    team_ids: list[int]  # 本块包含的班组（常白班合并时有两个）
    shift_date: date  # 本班组当前（或下一个）班次
    shift_kind: str
    on_duty: bool
    prev_team_ids: list[int]  # 上一班（交给本班组的班组）
    next_team_id: int | None  # 默认移交对象
    received: list[TaskOut]  # 别的班组移交过来、尚未完成
    todo: list[TaskOut]  # 本班组自己的未完成任务
    done_recent: list[TaskOut]  # 本班完成的（不在班时：它上一个班完成的）
    done_shift_date: date  # done_recent 对应的班次
    done_shift_kind: str


# ---------------- 翻译 / 术语表 ----------------
class ManualTranslation(BaseModel):
    field: Literal["content", "leftover", "discard_reason"]
    lang: Lang
    text: str = Field(min_length=1, max_length=5000)


class TranslationStatus(BaseModel):
    configured: bool
    model: str
    counts: dict[str, int]


class GlossaryIn(BaseModel):
    zh: str = Field(min_length=1, max_length=200)
    sr: str = Field(min_length=1, max_length=200)
    en: str = Field(min_length=1, max_length=200)
    category: str = Field(default="", max_length=50)
    note: str = Field(default="", max_length=200)


class GlossaryOut(GlossaryIn):
    model_config = ConfigDict(from_attributes=True)
    id: int
    updated_at: UTCDateTime


class ImportResult(BaseModel):
    added: int
    updated: int
    skipped: int


TaskOut.model_rebuild()
