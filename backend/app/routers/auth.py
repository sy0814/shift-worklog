"""登录：
- 个人账号（管理员、班长、副班长等「个人账号」角色）：用户名 + 密码
- 班组公共账号（成员等「班组账号」角色）：选班组 → 点自己的头像 → 输入自己的密码（个人密码，4～6 位数字也行）
连续输错 5 次锁定 10 分钟（只锁这一个人）。
"""

from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from .. import app_settings, audit, departments, permissions
from ..db import get_db
from ..models import Role, Team, User, Worker, utcnow
from ..schemas import MeOut, MeUpdate, PasswordChange, RoleBrief, TokenOut
from ..security import avatar_url, create_token, get_current_user, hash_password, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])

MAX_FAILS = 5
LOCK_MINUTES = 10


def login_mode(db: Session, user: User) -> str:
    """这个账号怎么登录：admin / password（个人账号）/ pin（班组公共账号 + 个人密码）。"""
    if user.role == "admin":
        return "password"
    role = permissions.role_of(db, db.get(Worker, user.worker_id) if user.worker_id else None)
    return role.login_mode if role else "pin"


def me_out(db: Session, user: User) -> MeOut:
    w = permissions.who(db, user)
    role = None
    if user.role != "admin":
        r = permissions.role_of(db, db.get(Worker, user.worker_id) if user.worker_id else None)
        role = RoleBrief.model_validate(r, from_attributes=True) if r else None
    perms = {k: "all" for k in permissions.PERMS} if w.is_admin else w.perms
    return MeOut(**MeOut.model_validate(user, from_attributes=True).model_dump(
        exclude={"role_info", "perms", "group_team_ids", "department_id", "can_switch_dept"}),
                 role_info=role, perms=perms, group_team_ids=sorted(w.group or []), department_id=w.dept_id,
                 can_switch_dept=departments.can_switch(db, user))


def _check_password(db: Session, user: User | None, password: str) -> User:
    """校验密码并处理锁定；失败抛 401 / 423。"""
    now = utcnow()
    if user is None or not user.is_active:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid username or password")
    locked = user.locked_until
    if locked is not None and locked.tzinfo is None:
        from datetime import timezone

        locked = locked.replace(tzinfo=timezone.utc)
    if locked and locked > now:
        mins = int((locked - now).total_seconds() // 60) + 1
        raise HTTPException(status.HTTP_423_LOCKED, f"account locked for {mins} min")
    if not verify_password(password, user.password_hash):
        user.failed_logins = (user.failed_logins or 0) + 1
        if user.failed_logins >= MAX_FAILS:
            user.failed_logins = 0
            user.locked_until = now + timedelta(minutes=LOCK_MINUTES)
            audit.log(db, user_id=None, action="locked", entity="user", entity_id=user.id)
        db.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid username or password")
    user.failed_logins = 0
    user.locked_until = None
    user.last_login_at = now
    return user


@router.post("/login", response_model=TokenOut)
def login(form: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)):
    """个人账号登录。成员（班组账号）请用 /pin。"""
    user = db.scalar(select(User).where(User.username == form.username))
    if user is not None and login_mode(db, user) == "pin":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "use team login")
    user = _check_password(db, user, form.password)
    audit.log(db, user_id=user.id, action="login", entity="user", entity_id=user.id)
    db.commit()
    return TokenOut(access_token=create_token(user), user=me_out(db, user))


# ---------------- 班组公共账号 ----------------
class TeamLoginTeam(BaseModel):
    id: int
    department_id: int
    name_zh: str
    name_sr: str
    name_en: str
    people: int


class TeamLoginPerson(BaseModel):
    user_id: int
    name: str
    avatar_url: str | None
    locked: bool


def _pin_accounts(db: Session, team_id: int | None = None) -> list[tuple[User, Worker]]:
    pin_roles = {r.id for r in db.scalars(select(Role).where(Role.login_mode == "pin"))}
    member = db.scalar(select(Role.id).where(Role.code == "member"))
    q = (select(User, Worker).join(Worker, Worker.id == User.worker_id)
         .where(User.is_active.is_(True), Worker.is_active.is_(True), User.role == "staff"))
    if team_id is not None:
        q = q.where(Worker.team_id == team_id)
    out = []
    for u, w in db.execute(q.order_by(Worker.name)).all():
        if (w.role_id or member) in pin_roles:
            out.append((u, w))
    return out


@router.get("/teams", response_model=list[TeamLoginTeam])
def login_teams(department_id: int | None = None, db: Session = Depends(get_db)):
    """登录页「班组账号」：有成员开了账号的班组（不需要登录）。给了车间就只列这个车间的。"""
    counts: dict[int, int] = {}
    for _u, w in _pin_accounts(db):
        if w.team_id:
            counts[w.team_id] = counts.get(w.team_id, 0) + 1
    q = select(Team).order_by(Team.sort_order)
    if department_id is not None:
        q = q.where(Team.department_id == department_id)
    return [TeamLoginTeam(id=t.id, department_id=t.department_id, name_zh=t.name_zh, name_sr=t.name_sr,
                          name_en=t.name_en, people=counts[t.id])
            for t in db.scalars(q) if counts.get(t.id)]


@router.get("/teams/{team_id}/people", response_model=list[TeamLoginPerson])
def login_people(team_id: int, db: Session = Depends(get_db)):
    """选了班组后，列出这个班组可以登录的人（头像 + 名字）。"""
    now = utcnow()
    out = []
    for u, w in _pin_accounts(db, team_id):
        lk = u.locked_until
        if lk is not None and lk.tzinfo is None:
            from datetime import timezone

            lk = lk.replace(tzinfo=timezone.utc)
        out.append(TeamLoginPerson(user_id=u.id, name=w.name, avatar_url=avatar_url(w.id, w.avatar_path) if w.avatar_path else None,
                                   locked=bool(lk and lk > now)))
    return out


class PinLogin(BaseModel):
    user_id: int
    pin: str = Field(min_length=1, max_length=100)


@router.post("/pin", response_model=TokenOut)
def pin_login(body: PinLogin, db: Session = Depends(get_db)):
    user = db.get(User, body.user_id)
    if user is None or user.role == "admin" or login_mode(db, user) != "pin":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid username or password")
    user = _check_password(db, user, body.pin)
    audit.log(db, user_id=user.id, action="login", entity="user", entity_id=user.id, extra={"via": "team"})
    db.commit()
    return TokenOut(access_token=create_token(user), user=me_out(db, user))


def check_secret(db: Session, user: User, secret: str) -> None:
    """个人账号密码至少 6 位；班组账号的个人密码至少 4 位。"""
    n = 4 if login_mode(db, user) == "pin" else 6
    if len(secret) < n:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"password must be at least {n} characters")


# ---------------- 当前用户 ----------------
@router.get("/me", response_model=MeOut)
def me(user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    return me_out(db, user)


@router.patch("/me", response_model=MeOut)
def update_me(body: MeUpdate, user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    changes = body.model_dump(exclude_none=True)
    if user.worker_id:
        changes.pop("full_name", None)  # 名字以名册为准
    audit.log_changes(db, user, changes, user_id=user.id, entity="user", entity_id=user.id)
    db.commit()
    return me_out(db, user)


@router.post("/change-password", status_code=204)
def change_password(body: PasswordChange, user: User = Depends(get_current_user),
                    db: Session = Depends(get_db)):
    if not verify_password(body.old_password, user.password_hash):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "wrong old password")
    check_secret(db, user, body.new_password)
    if body.new_password == body.old_password or body.new_password == app_settings.default_password(db):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "choose a different password")
    user.password_hash = hash_password(body.new_password)
    user.must_change_password = False
    audit.log(db, user_id=user.id, action="change_password", entity="user", entity_id=user.id)
    db.commit()
