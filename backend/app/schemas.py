from datetime import date, datetime, time, timezone
from typing import Annotated, Literal

from pydantic import AfterValidator, BaseModel, ConfigDict, Field


def _utc(d: datetime) -> datetime:
    # SQLite 读回来的是 naive 时间，库里统一存 UTC
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d


UTCDateTime = Annotated[datetime, AfterValidator(_utc)]

Lang = Literal["zh", "sr", "en"]
Role = Literal["admin", "leader"]


class ORM(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class TeamOut(ORM):
    id: int
    code: str
    name_zh: str
    name_sr: str
    name_en: str
    kind: str
    cycle_offset: int | None


class UserOut(ORM):
    id: int
    username: str
    full_name: str
    role: str
    team_id: int | None
    lang: str
    is_active: bool
    created_at: UTCDateTime


class TokenOut(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: UserOut


class UserCreate(BaseModel):
    username: str = Field(min_length=2, max_length=50, pattern=r"^[A-Za-z0-9_.-]+$")
    password: str = Field(min_length=6, max_length=100)
    full_name: str = Field(min_length=1, max_length=100)
    role: Role = "leader"
    team_id: int | None = None
    lang: Lang = "zh"


class UserUpdate(BaseModel):
    full_name: str | None = Field(default=None, min_length=1, max_length=100)
    role: Role | None = None
    team_id: int | None = None
    lang: Lang | None = None
    is_active: bool | None = None


class PasswordReset(BaseModel):
    password: str = Field(min_length=6, max_length=100)


class PasswordChange(BaseModel):
    old_password: str
    new_password: str = Field(min_length=6, max_length=100)


class MeUpdate(BaseModel):
    lang: Lang | None = None
    full_name: str | None = Field(default=None, min_length=1, max_length=100)


class ShiftConfigOut(ORM):
    base_date: date
    day_start: time
    middle_start: time
    night_start: time


class ShiftConfigIn(BaseModel):
    base_date: date
    day_start: time
    middle_start: time
    night_start: time
    # 基准日各倒班班组在循环中的位置 0..7，键为 team_id
    offsets: dict[int, int]


class HolidayIO(ORM):
    day: date
    name: str = ""


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


class WorkerCreate(BaseModel):
    name: str = Field(min_length=1, max_length=100)
    employee_no: str | None = Field(default=None, max_length=50)
    team_id: int | None = None


class WorkerBulkCreate(BaseModel):
    names: list[str] = Field(min_length=1, max_length=500)
    team_id: int | None = None


class WorkerUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=100)
    employee_no: str | None = Field(default=None, max_length=50)
    team_id: int | None = None
    is_active: bool | None = None


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
    start_at: datetime | None = None
    end_at: datetime | None = None


class TaskStatusChange(BaseModel):
    status: Literal["not_started", "in_progress", "done"]


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


class TaskOut(BaseModel):
    id: int
    client_id: str
    content: Trilingual
    source_lang: str
    leftover: Trilingual
    leftover_source_lang: str | None
    translation_status: str
    team_id: int
    origin_team_id: int
    source_task_id: int | None
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
    workers: list[WorkerOut]
    attachments: list[AttachmentOut]
    can_edit: bool


class TaskPage(BaseModel):
    items: list[TaskOut]
    total: int


class HistoryOut(AuditOut):
    user_name: str | None
