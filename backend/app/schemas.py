from datetime import date, datetime, time
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

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
    created_at: datetime


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
    at: datetime
    user_id: int | None
    action: str
    entity: str
    entity_id: str
    field: str | None
    old_value: str | None
    new_value: str | None
