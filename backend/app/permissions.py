"""角色权限：所有「谁能做什么」的判断都在这里。

每个角色（roles 表）有一张权限表 {权限: 范围}：
  none = 不能；self = 只限自己（自己是带队人 / 参与人员的任务、自己传的照片）；
  team = 本班组（含当天和本班组合并显示的班组，例如常白班 ↔ 白班主班组）；all = 全部班组。
管理员（users.role == "admin"）拥有全部权限，不看角色。
名册里没有设角色的人按「成员」角色算。
"""

from dataclasses import dataclass
from datetime import timedelta

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import Role, Task, User, Worker

SCOPES = ("none", "self", "team", "all")
RANK = {s: i for i, s in enumerate(SCOPES)}

# 权限 → 可选的范围（顺序 = 页面上的列顺序）
PERMS: dict[str, tuple[str, ...]] = {
    "task.view": ("team", "all"),  # 看任务（任务列表、交接班、警示）
    "task.create": ("none", "team", "all"),  # 新建任务
    "task.edit": ("none", "self", "team", "all"),  # 改内容、带队人、参与人员、时间
    "task.status": ("none", "self", "team", "all"),  # 开始 / 完成
    "task.handover": ("none", "team", "all"),  # 移交
    "task.discard": ("none", "team", "all"),  # 废弃
    "task.edit_done": ("none", "team", "all"),  # 改已完成的任务（含重新打开）
    "photo.upload": ("none", "self", "team", "all"),  # 传照片
    "photo.delete": ("none", "self", "team", "all"),  # 删照片（self = 只删自己传的）
    "translation.correct": ("none", "team", "all"),  # 校对译文
    "attendance.edit": ("none", "team", "all"),  # 改出勤、两人换班、批量安排
    "overtime.edit": ("none", "team", "all"),  # 设置加班
    "schedule.team_shift": ("none", "team", "all"),  # 班组调班（整个班组改班 / 两个班组互换）
    "inspection.manage": ("none", "team", "all"),  # 定期巡查项（team = 固定派给本班组的）
    "export": ("none", "team", "all"),  # 导出 Excel
    "worker.avatar": ("none", "team", "all"),  # 改员工头像
    "worker.pin": ("none", "team", "all"),  # 重设成员的个人密码
    "equipment.manage": ("none", "all"),  # 设备台账：新增、修改、导入、停用（看设备所有人都可以）
    "project.manage": ("none", "team", "all"),  # 建项目、加子项目、改派（team = 子项目只能分给本班组和合并的班组；all = 可以分给任何班组）
}

LEADER_PERMS = {
    "task.view": "all", "task.create": "team", "task.edit": "team", "task.status": "team",
    "task.handover": "team", "task.discard": "team", "task.edit_done": "none",
    "photo.upload": "team", "photo.delete": "team", "translation.correct": "team",
    "attendance.edit": "team", "overtime.edit": "team", "schedule.team_shift": "team",
    "inspection.manage": "team", "export": "team", "worker.avatar": "team", "worker.pin": "team",
    "project.manage": "team", "equipment.manage": "all",
}
MEMBER_PERMS = {k: ("team" if k == "task.view" else "self" if k in ("task.status", "photo.upload", "photo.delete")
                    else "none") for k in PERMS}

# 内置角色：班长、副班长（权限和以前的班长账号一样）、成员（只能开始 / 完成自己的任务、传照片）
BUILTIN_ROLES = [
    # code, zh, sr, en, 权限, 登录方式, 首页单独显示
    ("leader", "班长", "Šef smene", "Shift leader", LEADER_PERMS, "password", True),
    ("deputy", "副班长", "Zamenik šefa", "Deputy leader", LEADER_PERMS, "password", True),
    ("member", "成员", "Član ekipe", "Team member", MEMBER_PERMS, "pin", False),
]


def normalize(perms: dict) -> dict:
    """补齐缺的权限（按最小范围），去掉不认识的、范围不合法的。"""
    out = {}
    for k, allowed in PERMS.items():
        v = perms.get(k)
        out[k] = v if v in allowed else allowed[0]
    return out


@dataclass
class Who:
    """当前用户的权限上下文（一次请求里算一次）。"""

    user: User
    perms: dict[str, str]  # 管理员为空 dict
    worker_id: int | None
    group: set[int] | None  # 本班组 + 合并显示的班组；管理员为 None

    @property
    def is_admin(self) -> bool:
        return self.user.role == "admin"

    def scope(self, perm: str) -> str:
        return "all" if self.is_admin else self.perms.get(perm, "none")

    def has(self, perm: str) -> bool:
        return self.scope(perm) != "none"

    def team_ok(self, perm: str, team_id: int | None) -> bool:
        """不涉及「自己」的权限：能不能对这个班组做。"""
        s = self.scope(perm)
        return s == "all" or (s in ("team",) and team_id is not None and team_id in (self.group or set()))

    def task_ok(self, perm: str, task: Task) -> bool:
        """对这条任务能不能做 perm。"""
        s = self.scope(perm)
        if s == "all":
            return True
        if s == "team" and task.team_id in (self.group or set()):
            return True
        if s in ("self", "team") and self.worker_id is not None:
            return self.worker_id == task.lead_worker_id or any(w.id == self.worker_id for w in task.workers)
        return False

    def visible_team_ids(self) -> set[int] | None:
        """能看到哪些班组的任务。None = 全部。"""
        return None if self.scope("task.view") == "all" else set(self.group or set())


def role_of(db: Session, worker: Worker | None) -> Role | None:
    if worker is None:
        return None
    if worker.role_id:
        r = db.get(Role, worker.role_id)
        if r is not None:
            return r
    return db.scalar(select(Role).where(Role.code == "member"))


def group_ids(db: Session, team_id: int | None) -> set[int]:
    """本班组 + 合并显示的班组：今天它上的那个班、首页交接班正在显示的那个班（当前或下一个）；
    昨天上夜班的话，凌晨也算昨天夜班合并的。"""
    from .schedule_service import load_schedule, local_now

    if team_id is None:
        return set()
    sched = load_schedule(db)
    team = sched.team(team_id)
    if team is None:
        return {team_id}
    now = local_now()
    today = now.date()
    out = {team_id} | {t.id for t in sched.paired_teams(team, today)}
    # 首页交接班显示的是它当前在上的班；不在班就是它的下一个班（例如常白班 15:00 下班后显示明天和它合并的班组）
    d, k = sched.shift_at(now)
    try:
        sd, sk = (d, k) if sched.is_on(team, d, k) else sched.next_shift_of_team(team, d, k)
        out |= {t.id for t in sched.paired_teams(team, sd, sk)}
    except ValueError:  # 不固定班组没安排班
        pass
    yesterday = today - timedelta(days=1)
    if sched.shift_of(team, yesterday) == "night":
        out |= {t.id for t in sched.paired_teams(team, yesterday)}
    return out


def who(db: Session, user: User) -> Who:
    if user.role == "admin":
        return Who(user, {}, user.worker_id, None)
    worker = db.get(Worker, user.worker_id) if user.worker_id else None
    role = role_of(db, worker)
    perms = normalize(role.permissions if role else MEMBER_PERMS)
    team_id = worker.team_id if worker else user.team_id
    return Who(user, perms, user.worker_id, group_ids(db, team_id))


def require(ok: bool, msg: str = "permission denied") -> None:
    if not ok:
        raise HTTPException(status.HTTP_403_FORBIDDEN, msg)


def ensure_builtin_roles(db: Session) -> None:
    """第一次启动（或迁移后）补上内置角色。"""
    have = {r.code for r in db.scalars(select(Role))}
    for i, (code, zh, sr, en, perms, mode, top) in enumerate(BUILTIN_ROLES):
        if code not in have:
            db.add(Role(code=code, name_zh=zh, name_sr=sr, name_en=en, permissions=dict(perms), login_mode=mode,
                        show_on_top=top, sort_order=i, is_builtin=True))
    db.flush()
