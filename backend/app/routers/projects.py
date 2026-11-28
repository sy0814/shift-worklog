"""项目：建项目、加子项目（分给班组或具体的人）、改派、查看进度。

权限（角色权限里的「建项目 / 管项目」project.manage）：
  team = 能建项目，子项目只能分给本班组和当天合并显示的班组（或这些班组的人）；all = 可以分给任何班组；
  改项目、加子项目、改派：项目所属班组在自己范围内。
"""

from datetime import date, datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import or_, select
from sqlalchemy.orm import Session, selectinload

from .. import audit, permissions, project_service, translation_service
from ..db import get_db
from ..models import Project, Task, Team, User, Worker, utcnow
from ..schedule_service import load_schedule, local_now
from ..departments import get_dept
from .. import departments
from ..schemas import Lang, TaskOut, Trilingual, UTCDateTime
from ..security import get_current_user
from ..worker_history import Timelines
from .tasks import LANGS, OPEN, _get_task, tasks_out

router = APIRouter(prefix="/api/projects", tags=["projects"])


class SubIn(BaseModel):
    content: str = Field(min_length=1, max_length=5000)
    team_id: int | None = None  # 分给班组（班长再安排人）
    worker_id: int | None = None  # 或直接分给某个人


class ProjectIn(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    lang: Lang = "zh"
    transferable: bool = True
    deadline: date | None = None
    team_id: int | None = None  # 项目归哪个班组（管理员 / 范围是全部班组的可以选；默认自己的班组）
    subs: list[SubIn] = Field(default_factory=list, max_length=200)
    start_at: datetime | None = None  # 计划开始时间（空 = 马上）；子项目到「开始时间 - lead_minutes」才出现在待办里
    lead_minutes: int = Field(default=30, ge=0, le=1440)


class ProjectUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    lang: Lang | None = None
    transferable: bool | None = None
    deadline: date | None = None
    start_at: datetime | None = None
    lead_minutes: int | None = Field(default=None, ge=0, le=1440)


class SubsIn(BaseModel):
    lang: Lang = "zh"
    subs: list[SubIn] = Field(min_length=1, max_length=200)


class AssignIn(BaseModel):
    team_id: int | None = None
    worker_id: int | None = None


class ProjectOut(BaseModel):
    id: int
    name: Trilingual
    source_lang: str
    translation_status: str
    transferable: bool
    team_id: int
    deadline: date | None
    start_at: UTCDateTime | None = None
    lead_minutes: int = 30
    open_items: bool = False
    shift_date: date | None = None
    shift_kind: str | None = None
    closed_empty: bool = False
    can_add: bool = False  # 能不能往里加小项目（「当班自己加」的项目：这个班组能新建任务的人也能加）
    created_by_name: str
    created_at: UTCDateTime
    closed_at: UTCDateTime | None
    total: int
    done: int
    discarded: int
    open: int
    can_manage: bool


class ProjectDetail(ProjectOut):
    subs: list[TaskOut]


class PersonSlot(BaseModel):
    worker_id: int
    next_date: date | None  # 下一个（或正在上的）班
    next_kind: str | None
    on_now: bool  # 现在这个班就在上


def _out(db: Session, p: Project, prog, who, names) -> ProjectOut:
    return ProjectOut(
        id=p.id, name=Trilingual(zh=p.name_zh, sr=p.name_sr, en=p.name_en), source_lang=p.source_lang,
        translation_status=p.translation_status, transferable=p.transferable, team_id=p.team_id, deadline=p.deadline,
        start_at=p.start_at, lead_minutes=p.lead_minutes, open_items=p.open_items, shift_date=p.shift_date,
        shift_kind=p.shift_kind, closed_empty=p.closed_empty, can_add=_can_add(who, p),
        created_by_name=names.get(p.created_by, ""), created_at=p.created_at, closed_at=p.closed_at,
        total=prog.total, done=prog.done, discarded=prog.discarded, open=prog.open,
        can_manage=who.team_ok("project.manage", p.team_id))


def _utc(d: datetime | None) -> datetime | None:
    """页面传来的时间没带时区就当 UTC（前端都传 ISO 带 Z）。"""
    if d is not None and d.tzinfo is None:
        return d.replace(tzinfo=timezone.utc)
    return d


def _can_add(who, p: Project) -> bool:
    if p.closed_at is not None and p.closed_empty:
        return False
    return who.team_ok("project.manage", p.team_id) or (p.open_items and who.team_ok("task.create", p.team_id))


def _names(db: Session) -> dict[int, str]:
    return dict(db.execute(select(User.id, User.full_name)).all())


def _get(db: Session, pid: int) -> Project:
    p = db.get(Project, pid)
    if p is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return p


def _target_team(db: Session, sub: SubIn | AssignIn) -> tuple[int, Worker | None]:
    """子项目分给谁：班组，或某个人（那就是这个人今天所在的班组）。"""
    if (sub.team_id is None) == (sub.worker_id is None):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "give either team_id or worker_id")
    if sub.worker_id is not None:
        w = db.get(Worker, sub.worker_id)
        if w is None or not w.is_active:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown worker")
        team = Timelines(db, [w]).on(w.id, local_now().date()).team_id or w.team_id
        if team is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "worker has no team")
        return team, w
    if db.get(Team, sub.team_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "team not found")
    return sub.team_id, None


def _check_target(who, team_id: int) -> None:
    if not who.team_ok("project.manage", team_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "cannot assign to that team")


def _visible(db: Session, who, p: Project) -> bool:
    vis = who.visible_team_ids()
    if vis is None or p.team_id in vis:
        return True
    return db.scalar(select(Task.id).where(Task.project_id == p.id, Task.status != "handed_over",
                                           Task.team_id.in_(vis)).limit(1)) is not None


@router.get("", response_model=list[ProjectOut])
def list_projects(state: str = Query(default="open", pattern="^(open|closed|all)$"), db: Session = Depends(get_db),
                  user: User = Depends(get_current_user), dept: int | None = Depends(get_dept)):
    """当前车间的项目（项目属于本车间的班组，或者有子项目在本车间），再按能看的范围筛。"""
    who = permissions.who(db, user)
    q = select(Project)
    if state == "open":
        q = q.where(Project.closed_at.is_(None))
    elif state == "closed":
        q = q.where(Project.closed_at.is_not(None))
    vis = who.visible_team_ids()
    if vis is None:  # 能看全厂的人：看当前车间的
        vis = departments.team_ids(db, dept)
    in_my_team = select(Task.project_id).where(Task.project_id.is_not(None), Task.status != "handed_over",
                                               Task.team_id.in_(vis))
    q = q.where(or_(Project.team_id.in_(vis), Project.id.in_(in_my_team)))
    rows = list(db.scalars(q.order_by(Project.closed_at.is_not(None), Project.deadline.is_(None), Project.deadline,
                                      Project.id.desc()).limit(300)))
    prog = project_service.progress(db, [p.id for p in rows])
    if any(project_service.refresh_closed(db, p, prog[p.id]) for p in rows):
        db.commit()
    names = _names(db)
    return [_out(db, p, prog[p.id], who, names) for p in rows]


@router.post("", response_model=ProjectDetail, status_code=201)
def create_project(body: ProjectIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    who = permissions.who(db, user)
    permissions.require(who.has("project.manage"))
    team_id = body.team_id if body.team_id is not None and who.team_ok("project.manage", body.team_id) else user.team_id
    if team_id is None:  # 管理员没选班组：用第一个子项目的班组
        team_id = next((_target_team(db, s)[0] for s in body.subs), None)
    if team_id is None or db.get(Team, team_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "team_id required")
    targets = [_target_team(db, s) for s in body.subs]
    for tid, _w in targets:
        _check_target(who, tid)
    now = utcnow()
    p = Project(source_lang=body.lang, translation_status="pending", transferable=body.transferable, team_id=team_id,
                deadline=body.deadline, created_by=user.id, updated_by=user.id, created_at=now, updated_at=now,
                start_at=_utc(body.start_at) if body.start_at and _utc(body.start_at) > now else None,
                lead_minutes=body.lead_minutes)
    setattr(p, f"name_{body.lang}", body.name.strip())
    db.add(p)
    db.flush()
    audit.log(db, user_id=user.id, action="create", entity="project", entity_id=p.id,
              new={"name": body.name.strip(), "transferable": body.transferable, "team_id": team_id,
                   "deadline": str(body.deadline) if body.deadline else None, "subs": len(body.subs),
                   "start_at": p.start_at.isoformat() if p.start_at else None, "lead_minutes": body.lead_minutes})
    subs = [project_service.create_sub(db, p, s.content, body.lang, user.id, team_id=tid, worker=w)
            for s, (tid, w) in zip(body.subs, targets)]
    db.commit()
    translation_service.enqueue_project(p.id)
    for t in subs:
        translation_service.enqueue(t.id)
    return get_project(p.id, db, user)


@router.get("/people", response_model=list[PersonSlot])
def people(db: Session = Depends(get_db), user: User = Depends(get_current_user),
           dept: int | None = Depends(get_dept)):
    """分给具体的人时用（当前车间的人）：每个人下一个（或正在上的）班，休息的人能看出来。"""
    sched = load_schedule(db)
    now = local_now()
    d, k = sched.shift_at(now)
    out = []
    for w in db.scalars(select(Worker).where(Worker.is_active.is_(True), Worker.department_id == dept)):
        slot = project_service.next_slot_of_worker(db, sched, w, now)
        out.append(PersonSlot(worker_id=w.id, next_date=slot[0] if slot else None, next_kind=slot[1] if slot else None,
                              on_now=slot == (d, k)))
    return out


@router.get("/{pid}", response_model=ProjectDetail)
def get_project(pid: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = _get(db, pid)
    who = permissions.who(db, user)
    permissions.require(_visible(db, who, p), "not your team")
    prog = project_service.progress(db, [p.id])[p.id]
    if project_service.refresh_closed(db, p, prog):
        db.commit()
    subs = list(db.scalars(select(Task).options(selectinload(Task.workers), selectinload(Task.attachments))
                           .where(Task.project_id == p.id, Task.status != "handed_over").order_by(Task.id)))
    base = _out(db, p, prog, who, _names(db))
    return ProjectDetail(**base.model_dump(), subs=tasks_out(db, subs, user))


@router.patch("/{pid}", response_model=ProjectDetail)
def update_project(pid: int, body: ProjectUpdate, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = _get(db, pid)
    who = permissions.who(db, user)
    permissions.require(who.team_ok("project.manage", p.team_id))
    data = body.model_dump(exclude_unset=True)
    changes = {k: data[k] for k in ("transferable", "deadline", "lead_minutes") if k in data}
    if "start_at" in data:
        st = _utc(data["start_at"])
        changes["start_at"] = st if st and st > utcnow() else None
    renamed = False
    if data.get("name"):
        lang = data.get("lang") or p.source_lang
        name = data["name"].strip()
        if getattr(p, f"name_{lang}") != name or p.source_lang != lang:
            changes |= {f"name_{l}": None for l in LANGS} | {f"name_{lang}": name, "source_lang": lang,
                                                              "translation_status": "pending"}
            renamed = True
    if audit.log_changes(db, p, changes, user_id=user.id, entity="project", entity_id=p.id):
        p.updated_by, p.updated_at = user.id, utcnow()
        if "start_at" in changes or "lead_minutes" in changes:
            project_service.reschedule_subs(db, p)
    db.commit()
    if renamed:
        translation_service.enqueue_project(p.id)
    return get_project(p.id, db, user)


@router.post("/{pid}/subs", response_model=ProjectDetail)
def add_subs(pid: int, body: SubsIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    p = _get(db, pid)
    who = permissions.who(db, user)
    permissions.require(_can_add(who, p))
    if p.open_items:  # 当班自己加的小项目：都归这个项目的班组和那个班
        for s in body.subs:
            if s.worker_id is None:
                s.team_id = p.team_id
    targets = [_target_team(db, s) for s in body.subs]
    for tid, _w in targets:
        if not (p.open_items and tid == p.team_id):
            _check_target(who, tid)
    subs = [project_service.create_sub(db, p, s.content, body.lang, user.id, team_id=tid, worker=w)
            for s, (tid, w) in zip(body.subs, targets)]
    p.updated_by, p.updated_at = user.id, utcnow()
    project_service.refresh_closed(db, p)
    db.commit()
    for t in subs:
        translation_service.enqueue(t.id)
    return get_project(p.id, db, user)


@router.post("/{pid}/subs/{task_id}/assign", response_model=TaskOut)
def assign_sub(pid: int, task_id: int, body: AssignIn, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    """改派子项目：换班组（清掉原来的人，班长重新安排），或换成某个人（例如原来的人休息）。"""
    p = _get(db, pid)
    t = _get_task(db, task_id)
    if t.project_id != p.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if t.status not in OPEN:
        raise HTTPException(status.HTTP_409_CONFLICT, f"task is {t.status}")
    who = permissions.who(db, user)
    permissions.require(who.team_ok("project.manage", p.team_id) or who.team_ok("project.manage", t.team_id))
    team_id, worker = _target_team(db, body)
    _check_target(who, team_id)
    sched = load_schedule(db)
    now_local = local_now()
    slot = project_service.next_slot_of_worker(db, sched, worker, now_local) if worker else None
    if slot is None:
        team = sched.team(team_id)
        try:
            slot = sched.receiving_slot(team, now_local) if team else sched.shift_at(now_local)
        except ValueError:
            slot = sched.shift_at(now_local)
    names = dict(db.execute(select(Worker.id, Worker.name)).all())
    old = {"team_id": t.team_id, "lead": names.get(t.lead_worker_id), "shift": f"{t.shift_date} {t.shift_kind}"}
    t.team_id = team_id
    t.shift_date, t.shift_kind = slot
    t.workers = [worker] if worker else []
    t.lead_worker_id = worker.id if worker else None
    t.updated_by, t.updated_at = user.id, utcnow()
    audit.log(db, user_id=user.id, action="assign", entity="task", entity_id=t.id, field="assign", old=old,
              new={"team_id": team_id, "lead": worker.name if worker else None, "shift": f"{slot[0]} {slot[1]}"})
    db.commit()
    return tasks_out(db, [_get_task(db, t.id)], user)[0]
