"""任务：增删改、参与人员、状态流转、图片。所有改动写留痕。

权限：所有登录用户可查看全部任务；班长只能新建/修改本班组任务，管理员可改全部。
已移交 / 已废弃的任务不可再修改（移交、废弃见 handover.py）。
"""

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from pydantic import BaseModel
from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from fastapi.responses import FileResponse
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from .. import app_settings, audit, departments, permissions, translation_service
from ..departments import get_dept
from ..config import get_settings
from ..db import get_db
from ..images import InvalidImage, parse_exif_datetime, process_upload
from ..models import Attachment, AuditLog, InspectionTemplate, Task, TaskHandover, Team, User, Worker, utcnow
from ..schedule_service import load_schedule, local_now
from ..schemas import (
    AttachmentOut,
    AuditOut,
    HandoverInfo,
    HistoryOut,
    EquipmentBrief,
    ProjectBrief,
    TaskCreate,
    TaskOut,
    TaskPage,
    TaskStatusChange,
    TaskUpdate,
    Trilingual,
    WorkerOut,
)
from ..security import file_token, get_current_user, verify_file_token

router = APIRouter(prefix="/api", tags=["tasks"])

LANGS = ("zh", "sr", "en")
TERMINAL = {"handed_over", "discarded"}
OPEN = ("not_started", "in_progress")
TRANSITIONS = {
    "not_started": {"in_progress", "done"},
    "in_progress": {"not_started", "done"},
    "done": {"in_progress"},  # 重新打开
}


# ---------------- 工具 ----------------
def to_utc(d: datetime | None) -> datetime | None:
    """无时区的输入按工厂时区理解，统一转成 UTC。"""
    if d is None:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=get_settings().tz)
    return d.astimezone(timezone.utc)


def _upload_root() -> Path:
    return Path(get_settings().upload_dir)


def _names(db: Session) -> dict[int, str]:
    return dict(db.execute(select(User.id, User.full_name)).all())


def _att_out(a: Attachment, names: dict[int, str], can_delete: bool = False) -> AttachmentOut:
    t = file_token(a.id)
    base = f"/api/files/{a.id}"
    return AttachmentOut(
        id=a.id, client_id=a.client_id, filename=a.filename, width=a.width, height=a.height,
        taken_at=a.taken_at, taken_at_source=a.taken_at_source, uploaded_by=a.uploaded_by,
        uploaded_by_name=names.get(a.uploaded_by, ""), uploaded_at=a.uploaded_at,
        url_thumb=f"{base}/thumb?t={t}", url_view=f"{base}/view?t={t}",
        url_original=f"{base}/original?t={t}", can_delete=can_delete,
    )


def editable_team_ids(db: Session, user: User) -> set[int] | None:
    """本班组 + 合并显示的班组。None = 管理员（全部）。"""
    if user.role == "admin":
        return None
    team_id = permissions.who(db, user).group
    return set(team_id or set())


def task_perms(w: "permissions.Who | None", task: Task) -> dict[str, bool]:
    """当前用户对这条任务能做什么（按角色权限）。已完成的任务要有「改已完成的任务」权限；已移交 / 已废弃的不能再改
    （校对译文除外）。"""
    keys = ("edit", "status", "handover", "discard", "photo", "correct", "log")
    if w is None:
        return dict.fromkeys(keys, False)
    live = task.status not in TERMINAL
    open_ = task.status in OPEN
    done_ok = task.status != "done" or w.task_ok("task.edit_done", task)
    return {
        "edit": live and done_ok and w.task_ok("task.edit", task),
        "status": live and done_ok and w.task_ok("task.status", task),
        # 不可移交的任务、不可移交的项目的子项目不能移交
        "handover": open_ and w.task_ok("task.handover", task) and can_transfer(task),
        "discard": open_ and w.task_ok("task.discard", task),
        "photo": live and done_ok and w.task_ok("photo.upload", task),
        "correct": done_ok and w.task_ok("translation.correct", task),
        # 班次日志：能开始 / 完成或修改这条任务的人
        "log": live and done_ok and (w.task_ok("task.status", task) or w.task_ok("task.edit", task)),
    }


def can_transfer(task: Task) -> bool:
    """任务自己可移交，并且（是项目子项目时）项目也可移交。"""
    return bool(task.transferable) and not (task.project_id and task.project and not task.project.transferable)


def photo_delete_ok(w: "permissions.Who | None", task: Task, a: Attachment) -> bool:
    if w is None or task.status in TERMINAL:
        return False
    if task.status == "done" and not w.task_ok("task.edit_done", task):
        return False
    s = w.scope("photo.delete")
    if s == "self":
        return a.uploaded_by == w.user.id
    return w.task_ok("photo.delete", task)


def _aware(d: datetime) -> datetime:
    return d.replace(tzinfo=timezone.utc) if d.tzinfo is None else d


@dataclass
class OutCtx:
    """把一批任务转成 TaskOut 时需要的附加数据（一次查询，避免逐条查）。"""

    names: dict[int, str]
    ho_from: dict[int, TaskHandover]  # from_task_id → 移交记录
    ho_to: dict[int, TaskHandover]  # to_task_id → 移交记录
    overdue_hours: int
    overdue_handovers: int
    now: datetime
    inspections: dict[int, str]  # 巡查项 id → 名称
    who: "permissions.Who | None"  # 当前用户的权限
    projects: dict  # 项目 id → ProjectBrief
    equipment: dict  # 设备 id → EquipmentBrief


def _project_briefs(db: Session, ids: set[int]) -> dict:
    from .. import project_service
    from ..models import Project

    if not ids:
        return {}
    prog = project_service.progress(db, list(ids))
    return {p.id: ProjectBrief(id=p.id, name=Trilingual(zh=p.name_zh, sr=p.name_sr, en=p.name_en),
                               source_lang=p.source_lang, transferable=p.transferable,
                               done=prog[p.id].done + prog[p.id].discarded, total=prog[p.id].total)
            for p in db.scalars(select(Project).where(Project.id.in_(ids)))}


def _equipment_briefs(db: Session, ids: set[int]) -> dict:
    from ..models import Equipment

    if not ids:
        return {}
    return {e.id: EquipmentBrief(id=e.id, code=e.code, name=Trilingual(zh=e.name_zh, sr=e.name_sr, en=e.name_en),
                                 source_lang=e.source_lang)
            for e in db.scalars(select(Equipment).where(Equipment.id.in_(ids)))}


def _check_equipment(db: Session, eid: int | None) -> None:
    from ..models import Equipment

    if eid is not None and db.get(Equipment, eid) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown equipment")


def make_ctx(db: Session, tasks: list[Task], user: User | None = None) -> OutCtx:
    ids = [t.id for t in tasks]
    hos = db.scalars(select(TaskHandover).where(
        or_(TaskHandover.from_task_id.in_(ids), TaskHandover.to_task_id.in_(ids)))).all() if ids else []
    cfg = app_settings.get_all(db)
    insp_ids = {t.inspection_id for t in tasks if t.inspection_id}
    inspections = dict(db.execute(select(InspectionTemplate.id, InspectionTemplate.name)
                                  .where(InspectionTemplate.id.in_(insp_ids))).all()) if insp_ids else {}
    return OutCtx(
        inspections=inspections,
        who=permissions.who(db, user) if user is not None else None,
        projects=_project_briefs(db, {t.project_id for t in tasks if t.project_id}),
        equipment=_equipment_briefs(db, {t.equipment_id for t in tasks if t.equipment_id}),
        names=_names(db),
        ho_from={h.from_task_id: h for h in hos},
        ho_to={h.to_task_id: h for h in hos},
        overdue_hours=cfg["overdue_hours"],
        overdue_handovers=cfg["overdue_handovers"],
        now=utcnow(),
    )


def overdue_clause(db: Session, now: datetime):
    """SQL 条件：未完成且（从第一次录入起超过 N 小时 或 已移交 N 次及以上）。"""
    cfg = app_settings.get_all(db)
    return (Task.status.in_(OPEN)) & or_(
        Task.chain_started_at <= now - timedelta(hours=cfg["overdue_hours"]),
        Task.handover_count >= cfg["overdue_handovers"],
    )


def _ho_info(h: TaskHandover | None, incoming: bool, names: dict[int, str]) -> HandoverInfo | None:
    if h is None:
        return None
    return HandoverInfo(
        team_id=h.from_team_id if incoming else h.to_team_id,
        task_id=h.from_task_id if incoming else h.to_task_id,
        default_team_id=h.default_team_id, note=h.note, note_lang=h.note_lang,
        by_name=names.get(h.by_user_id, ""), at=h.at,
    )


def task_out(task: Task, user: User, ctx: OutCtx) -> TaskOut:
    names = ctx.names
    perms = task_perms(ctx.who, task)
    age = (ctx.now - _aware(task.chain_started_at)).total_seconds() / 3600
    overdue = task.status in OPEN and (age >= ctx.overdue_hours or task.handover_count >= ctx.overdue_handovers)
    return TaskOut(
        id=task.id, client_id=task.client_id,
        content=Trilingual(zh=task.content_zh, sr=task.content_sr, en=task.content_en),
        source_lang=task.source_lang,
        leftover=Trilingual(zh=task.leftover_zh, sr=task.leftover_sr, en=task.leftover_en),
        leftover_source_lang=task.leftover_source_lang,
        translation_status=task.translation_status,
        translation_error=task.translation_error if user.role == "admin" else None,
        manual_fields=list(task.manual_fields or []),
        team_id=task.team_id, origin_team_id=task.origin_team_id, source_task_id=task.source_task_id,
        inspection_id=task.inspection_id, inspection_name=ctx.inspections.get(task.inspection_id),
        status=task.status, shift_date=task.shift_date, shift_kind=task.shift_kind,
        start_at=task.start_at, end_at=task.end_at,
        confirmed_by=task.confirmed_by,
        confirmed_by_name=names.get(task.confirmed_by) if task.confirmed_by else None,
        confirmed_at=task.confirmed_at,
        created_by=task.created_by, created_by_name=names.get(task.created_by, ""),
        updated_by=task.updated_by, updated_by_name=names.get(task.updated_by, ""),
        recorded_at=task.recorded_at, created_at=task.created_at, updated_at=task.updated_at,
        lead=WorkerOut.model_validate(task.lead) if task.lead_worker_id and task.lead else None,
        workers=[WorkerOut.model_validate(w) for w in task.workers if w.id != task.lead_worker_id],
        attachments=[_att_out(a, names, photo_delete_ok(ctx.who, task, a)) for a in task.attachments],
        can_edit=perms["edit"],
        can_correct=perms["correct"],
        perms=perms,
        project=ctx.projects.get(task.project_id),
        equipment=ctx.equipment.get(task.equipment_id), transferable=can_transfer(task),
        chain_started_at=task.chain_started_at, handover_count=task.handover_count,
        age_hours=round(age, 1), overdue=overdue,
        handover_in=_ho_info(ctx.ho_to.get(task.id), True, names),
        handover_out=_ho_info(ctx.ho_from.get(task.id), False, names),
        discard_reason=Trilingual(zh=task.discard_reason_zh, sr=task.discard_reason_sr, en=task.discard_reason_en),
        discard_reason_lang=task.discard_reason_lang,
        discarded_by_name=names.get(task.discarded_by) if task.discarded_by else None,
        discarded_at=task.discarded_at,
    )


def tasks_out(db: Session, tasks: list[Task], user: User) -> list[TaskOut]:
    ctx = make_ctx(db, tasks, user)
    return [task_out(t, user, ctx) for t in tasks]


def one_out(db: Session, task: Task, user: User) -> TaskOut:
    return tasks_out(db, [task], user)[0]


def _get_task(db: Session, task_id: int) -> Task:
    task = db.get(Task, task_id, options=[selectinload(Task.workers), selectinload(Task.attachments)])
    if task is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return task


def _require(db: Session, task: Task, user: User, key: str = "edit") -> "permissions.Who":
    """检查对这条任务能不能做 key（edit / status / handover / discard / photo / correct），不能就抛错。"""
    if task.status in TERMINAL and key != "correct":
        raise HTTPException(status.HTTP_409_CONFLICT, f"task is {task.status}")
    w = permissions.who(db, user)
    if not task_perms(w, task)[key]:
        if task.status == "done" and not w.task_ok("task.edit_done", task):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "task is done; only admin can edit it")
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your team's task")
    return w


def _require_edit(db: Session, task: Task, user: User) -> None:  # 旧名字
    _require(db, task, user, "edit")


def _visible(w: "permissions.Who", task: Task) -> bool:
    vis = w.visible_team_ids()
    return vis is None or task.team_id in vis or w.task_ok("task.view", task) or (
        w.worker_id is not None and (task.lead_worker_id == w.worker_id or any(x.id == w.worker_id for x in task.workers)))


def assignable_ids(db: Session, sched, team_id: int, d, k: str) -> set[int]:
    """这个班次（d, k）里可以分配的人：本班组和合并显示的班组当班在岗的人（按出勤，含调班、来支援的人）。"""
    from .. import attendance_service as att

    team = sched.team(team_id)
    group = {t.id for t in sched.group_of(team, d, k)} if team else {team_id}
    group.add(team_id)
    # 这个班次的主班组那一组，还要算上「班组自己今天不上这个班、但人被单独安排来上」的人
    # （例如 4 班休息、人被叫来上白班却没写顶哪个班组）
    dept = team.dept if team else sched.depts()[0]
    main = sched.main_team_on(d, k, dept)
    slot_group = {t.id for t in sched.group_of(main, d, k)} if main else set()
    on_ids = {t.id for t in sched.teams_on(d, k)}  # 所有车间此刻在班的班组（被单独叫来的人不能是这些班组的）
    workers = list(db.scalars(select(Worker).where(Worker.is_active.is_(True))))
    eff = att.effective(db, workers, d - timedelta(days=1), d, sched)
    out = {w.id for w in workers
           if (a := eff[w.id][d]).status == "present" and a.shift_kind == k
           and (a.team_id in group or (team_id in slot_group and a.team_id not in on_ids))}
    # 算在别的班、但自定义上班时间有一段落在这个班次里的人（例如白班 07-12、14-17 的人在中班的前两小时），
    # 这个班次的主班组那一组也能给他安排任务（首页中班名单里也列着他）
    if team_id in slot_group:
        from .duty import _overlap

        start, end = sched.shift_window(d, k)
        for w in workers:
            if w.id not in out and (x := _overlap(sched, eff[w.id], d, k, start, end, None)) is not None \
                    and sched.team(x[0].team_id or w.team_id) is not None \
                    and sched.team(x[0].team_id or w.team_id).dept == dept:
                out.add(w.id)
    return out


def unrestricted(w: "permissions.Who") -> bool:
    """管理员、车间管理员（新建和修改任务的范围都是本车间或全厂）可以把任务分给任何人。"""
    return w.scope("task.edit") in ("dept", "all") and w.scope("task.create") in ("dept", "all")


def _check_assignable(db: Session, w: "permissions.Who", team_id: int, d, k: str, new_ids: set[int]) -> None:
    """班长只能把任务分给同一班次在岗的人（管理员 / 车间管理员不限）。"""
    if not new_ids or unrestricted(w):
        return
    bad = new_ids - assignable_ids(db, load_schedule(db), team_id, d, k)
    if bad:
        names = ", ".join(n for (n,) in db.execute(select(Worker.name).where(Worker.id.in_(bad))).all())
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"{names} is not on duty in this shift")


def _load_workers(db: Session, ids: list[int]) -> list[Worker]:
    ids = list(dict.fromkeys(ids))
    if not ids:
        return []
    ws = db.scalars(select(Worker).where(Worker.id.in_(ids))).all()
    if len(ws) != len(ids):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown worker")
    by_id = {w.id: w for w in ws}
    return [by_id[i] for i in ids]


def _check_times(start: datetime | None, end: datetime | None) -> None:
    if start and end and to_utc(end) < to_utc(start):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "end_at before start_at")


def _text_changes(prefix: str, task: Task, text: str | None, lang: str, retranslate: bool) -> tuple[dict, bool]:
    """修改某段文字。返回 (要写的列, 是否需要重新翻译)。

    retranslate=True：写入该语言列，其余两种语言清空待重新翻译（含人工校对过的）。
    retranslate=False：只改原文那一列，保留现有译文（换了原文语言时仍强制重新翻译）。
    """
    src_field = "source_lang" if prefix == "content" else "leftover_source_lang"
    text = (text or "").strip() or None
    if text is None:  # 只有遗留问题允许清空
        return {f"{prefix}_{l}": None for l in LANGS} | {src_field: None}, False
    if getattr(task, f"{prefix}_{lang}") == text and getattr(task, src_field) == lang:
        return {}, False
    if not retranslate and getattr(task, src_field) == lang:
        return {f"{prefix}_{lang}": text}, False
    changes = {f"{prefix}_{l}": None for l in LANGS if l != lang}
    changes[f"{prefix}_{lang}"] = text
    changes[src_field] = lang
    return changes, True


class AssignableOut(BaseModel):
    shift_date: date
    shift_kind: str
    restricted: bool  # True = 只能选 worker_ids 里的人（班长）；False = 谁都能选（管理员等）
    worker_ids: list[int]


@router.get("/assignable", response_model=AssignableOut)
def assignable(team_id: int | None = None, task_id: int | None = None, db: Session = Depends(get_db),
               user: User = Depends(get_current_user)):
    """新建 / 编辑任务时可以分配的人：同一班次在岗的人（本班组 + 合并显示的班组 + 来支援的人）。"""
    sched = load_schedule(db)
    w = permissions.who(db, user)
    if task_id:
        task = _get_task(db, task_id)
        team_id, d, k = task.team_id, task.shift_date, task.shift_kind
    else:
        team_id = team_id or user.team_id
        team = sched.team(team_id)
        if team is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "team not found")
        d, k = sched.recording_slot(team, local_now())
    restricted = not unrestricted(w)
    return AssignableOut(shift_date=d, shift_kind=k, restricted=restricted,
                         worker_ids=sorted(assignable_ids(db, sched, team_id, d, k)))


# ---------------- 任务 ----------------
@router.get("/tasks", response_model=TaskPage)
def list_tasks(
    team_id: int | None = None,
    all_departments: bool = False,  # 不限当前车间（能看全厂的人用）
    status_: list[str] | None = Query(default=None, alias="status"),
    date_from: str | None = None,
    date_to: str | None = None,
    worker_id: int | None = None,
    equipment_id: int | None = None,
    q: str | None = Query(default=None, max_length=100),
    overdue: bool = False,
    limit: int = Query(default=50, le=200),
    offset: int = 0,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
    dept: int | None = Depends(get_dept),
):
    query = select(Task)
    w = permissions.who(db, user)
    vis = w.visible_team_ids()
    if vis is not None:  # 只能看本班组（和合并班组）/ 本车间的任务，外加自己参与的
        mine = Task.workers.any(Worker.id == w.worker_id) if w.worker_id else False
        query = query.where(or_(Task.team_id.in_(vis), mine) if w.worker_id else Task.team_id.in_(vis))
    elif not team_id and not all_departments:  # 能看全厂的人：默认只列当前车间
        query = query.where(Task.team_id.in_(departments.team_ids(db, dept)))
    if team_id:
        query = query.where(Task.team_id == team_id)
    if status_:
        query = query.where(Task.status.in_(status_))
    if date_from:
        query = query.where(Task.shift_date >= date_from)
    if date_to:
        query = query.where(Task.shift_date <= date_to)
    if worker_id:
        query = query.where(Task.workers.any(Worker.id == worker_id))
    if equipment_id:
        query = query.where(Task.equipment_id == equipment_id)
    if overdue:
        query = query.where(overdue_clause(db, utcnow()))
    if q:
        like = f"%{q}%"
        query = query.where(or_(*[getattr(Task, f"{p}_{l}").ilike(like)
                                  for p in ("content", "leftover") for l in LANGS]))
    total = db.scalar(select(func.count()).select_from(query.subquery()))
    rows = db.scalars(
        query.options(selectinload(Task.workers), selectinload(Task.attachments))
        .order_by(Task.shift_date.desc(), Task.created_at.desc())
        .limit(limit).offset(offset)
    ).all()
    return TaskPage(items=tasks_out(db, list(rows), user), total=total)


@router.get("/tasks/{task_id}", response_model=TaskOut)
def get_task(task_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    task = _get_task(db, task_id)
    permissions.require(_visible(permissions.who(db, user), task), "not your team's task")
    return one_out(db, task, user)


@router.post("/tasks", response_model=TaskOut, status_code=201)
def create_task(body: TaskCreate, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    # 离线草稿可能重复提交：同一个 client_id 直接返回已有任务
    existing = db.scalar(select(Task).where(Task.client_id == body.client_id))
    if existing is not None:
        # 真正的重试内容一定相同；内容不同说明客户端出错，拒绝而不是悄悄返回别的任务
        # 翻译后原文可能被挪到模型判断的那一列，所以三列都比
        same = existing.created_by == user.id and body.content.strip() in \
            {existing.content_zh, existing.content_sr, existing.content_en}
        if not same:
            raise HTTPException(status.HTTP_409_CONFLICT, "client_id already used")
        return one_out(db, _get_task(db, existing.id), user)

    w = permissions.who(db, user)
    permissions.require(w.has("task.create"))
    if body.team_id is not None and w.team_ok("task.create", body.team_id):
        if db.get(Team, body.team_id) is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "team_id required")
        team_id = body.team_id
    elif user.role == "admin" or user.team_id is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "team_id required")
    else:
        team_id = user.team_id

    now = utcnow()
    recorded = to_utc(body.recorded_at) or now
    if not (now - timedelta(days=30) <= recorded <= now + timedelta(minutes=5)):
        recorded = now
    local = recorded.astimezone(get_settings().tz).replace(tzinfo=None)
    # 归属班次按「录入的班组」算：在班 → 当前班；刚下班 2 小时内 → 刚结束的班；否则 → 它的下一个班
    sched = load_schedule(db)
    team_info = next((x for x in sched.teams if x.id == team_id), None)
    shift_date, shift_kind = sched.recording_slot(team_info, local) if team_info else sched.shift_at(local)

    _check_times(body.start_at, body.end_at)
    start_at, end_at = to_utc(body.start_at), to_utc(body.end_at)
    if body.status in ("in_progress", "done") and start_at is None:
        start_at = recorded
    if body.status == "done" and end_at is None:
        end_at = max(recorded, start_at)

    task = Task(
        client_id=body.client_id, source_lang=body.lang, team_id=team_id, origin_team_id=team_id,
        status=body.status, shift_date=shift_date, shift_kind=shift_kind,
        start_at=start_at, end_at=end_at,
        confirmed_by=user.id if body.status == "done" else None,
        confirmed_at=now if body.status == "done" else None,
        created_by=user.id, updated_by=user.id, recorded_at=recorded, created_at=now, updated_at=now,
        translation_status="pending", chain_started_at=recorded, handover_count=0,
    )
    setattr(task, f"content_{body.lang}", body.content.strip())
    if body.leftover and body.leftover.strip():
        setattr(task, f"leftover_{body.lang}", body.leftover.strip())
        task.leftover_source_lang = body.lang
    lead_id = body.lead_worker_id
    member_ids = [i for i in body.worker_ids if i != lead_id]
    _check_assignable(db, w, team_id, shift_date, shift_kind, set(member_ids) | ({lead_id} if lead_id else set()))
    task.workers = _load_workers(db, member_ids + ([lead_id] if lead_id else []))
    task.lead_worker_id = lead_id
    _check_equipment(db, body.equipment_id)
    task.equipment_id = body.equipment_id
    task.transferable = body.transferable
    db.add(task)
    db.flush()
    audit.log(db, user_id=user.id, action="create", entity="task", entity_id=task.id, new={
        "content": body.content.strip(), "lang": body.lang, "team_id": team_id,
        "status": body.status, "worker_ids": member_ids, "lead_worker_id": lead_id, "equipment_id": body.equipment_id,
        "transferable": body.transferable,
        "start_at": start_at, "end_at": end_at, "leftover": task.leftover_source_lang and body.leftover.strip(),
        "recorded_at": recorded, "shift": f"{shift_date} {shift_kind}",
    })
    task.manual_fields = []
    db.commit()
    translation_service.enqueue(task.id)  # 放进翻译队列，由后台线程翻译
    return one_out(db, _get_task(db, task.id), user)


@router.patch("/tasks/{task_id}", response_model=TaskOut)
def update_task(task_id: int, body: TaskUpdate, db: Session = Depends(get_db),
                user: User = Depends(get_current_user)):
    task = _get_task(db, task_id)
    w = _require(db, task, user, "edit")
    data = body.model_dump(exclude_unset=True)
    lang = body.lang or user.lang
    changes: dict = {}
    text_changed: dict[str, bool] = {}  # 字段 → 是否重新翻译
    if "content" in data:
        if not data["content"] or not data["content"].strip():
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "content required")
        c, rt = _text_changes("content", task, data["content"], lang, body.retranslate)
        if c:
            changes |= c
            text_changed["content"] = rt
    if "leftover" in data:
        c, rt = _text_changes("leftover", task, data["leftover"], body.leftover_lang or lang, body.retranslate)
        if c:
            changes |= c
            text_changed["leftover"] = rt
    for f in ("start_at", "end_at"):
        if f in data:
            changes[f] = to_utc(data[f])
    if "equipment_id" in data:
        _check_equipment(db, data["equipment_id"])
        changes["equipment_id"] = data["equipment_id"]
    if data.get("transferable") is not None:
        changes["transferable"] = data["transferable"]
    _check_times(changes.get("start_at", task.start_at), changes.get("end_at", task.end_at))

    changed = audit.log_changes(db, task, changes, user_id=user.id, entity="task", entity_id=task.id)
    for field, rt in text_changed.items():
        translation_service.mark_text_changed(task, field, retranslate=rt)

    # 带队人员 / 参与人员（带队人也放进 workers，按「参与」统计时自动算上）
    if ("worker_ids" in data and data["worker_ids"] is not None) or "lead_worker_id" in data:
        old_lead = task.lead_worker_id
        old_members = [w.id for w in task.workers if w.id != old_lead]
        new_lead = data["lead_worker_id"] if "lead_worker_id" in data else old_lead
        new_members = data["worker_ids"] if data.get("worker_ids") is not None else old_members
        new_members = [i for i in dict.fromkeys(new_members) if i != new_lead]
        new_workers = _load_workers(db, new_members + ([new_lead] if new_lead else []))
        added = {x.id for x in new_workers} - {x.id for x in task.workers}
        _check_assignable(db, w, task.team_id, task.shift_date, task.shift_kind, added)
        names = dict(db.execute(select(Worker.id, Worker.name)).all())
        if new_lead != old_lead:
            audit.log(db, user_id=user.id, action="update", entity="task", entity_id=task.id,
                      field="lead_worker", old=names.get(old_lead), new=names.get(new_lead),
                      extra={"old_id": old_lead, "new_id": new_lead})
            task.lead_worker_id = new_lead
            changed = True
        if sorted(old_members) != sorted(new_members):
            audit.log(db, user_id=user.id, action="update", entity="task", entity_id=task.id,
                      field="workers", old=[names[i] for i in old_members], new=[names[i] for i in new_members],
                      extra={"old_ids": old_members, "new_ids": new_members})
            changed = True
        if sorted(w.id for w in task.workers) != sorted(w.id for w in new_workers):
            task.workers = new_workers

    if changed:
        task.updated_by = user.id
        task.updated_at = utcnow()
    db.commit()
    if task.translation_status == "pending":
        translation_service.enqueue(task.id)
    return one_out(db, _get_task(db, task.id), user)


@router.post("/tasks/{task_id}/status", response_model=TaskOut)
def change_status(task_id: int, body: TaskStatusChange, db: Session = Depends(get_db),
                  user: User = Depends(get_current_user)):
    task = _get_task(db, task_id)
    new = body.status
    if new == task.status and body.expect is not None:
        return one_out(db, task, user)  # 离线发件箱重发（上次其实已经成功，只是没收到回应）
    _require(db, task, user, "status")
    if new == task.status:
        return one_out(db, task, user)
    if body.expect is not None and body.expect != task.status:
        # 离线期间别人已经改了这条任务的状态
        raise HTTPException(status.HTTP_409_CONFLICT, f"task status changed meanwhile ({task.status})")
    if new not in TRANSITIONS.get(task.status, set()):
        raise HTTPException(status.HTTP_409_CONFLICT, f"cannot go from {task.status} to {new}")
    now = utcnow()
    if body.at is not None:  # 离线时点的：按点的时间记，但不能晚于现在、不早于 3 天前 / 任务录入时间
        at = to_utc(body.at)
        created = task.created_at
        if created is not None and created.tzinfo is None:  # SQLite 读出来没有时区，存的是 UTC
            created = created.replace(tzinfo=timezone.utc)
        lo = max(now - timedelta(days=3), created or now - timedelta(days=3))
        now = min(max(at, lo), now)
    changes: dict = {"status": new}
    if new == "in_progress" and task.start_at is None:
        changes["start_at"] = now
    if new == "done":
        if task.end_at is None:
            changes["end_at"] = now
        if task.start_at is None:
            changes["start_at"] = changes.get("end_at", task.end_at)
        changes["confirmed_by"] = user.id
        changes["confirmed_at"] = now
    if task.status == "done":  # 重新打开：清除完成信息
        changes |= {"end_at": None, "confirmed_by": None, "confirmed_at": None}
    if new == "not_started":
        changes["start_at"] = None
    audit.log_changes(db, task, changes, user_id=user.id, entity="task", entity_id=task.id,
                      action="status")
    task.updated_by = user.id
    task.updated_at = now
    db.commit()
    return one_out(db, _get_task(db, task.id), user)


@router.get("/tasks/{task_id}/history", response_model=list[HistoryOut])
def task_history(task_id: int, db: Session = Depends(get_db), _: User = Depends(get_current_user)):
    _get_task(db, task_id)
    names = _names(db)
    rows = db.scalars(select(AuditLog).where(AuditLog.entity == "task", AuditLog.entity_id == str(task_id))
                      .order_by(AuditLog.id)).all()
    return [HistoryOut(**AuditOut.model_validate(r).model_dump(), user_name=names.get(r.user_id))
            for r in rows]


# ---------------- 图片 ----------------
@router.post("/tasks/{task_id}/attachments", response_model=AttachmentOut, status_code=201)
async def upload_attachment(
    task_id: int,
    file: UploadFile = File(...),
    client_id: str = Form(..., pattern=r"^[0-9a-fA-F-]{36}$"),
    last_modified: int | None = Form(default=None),  # 浏览器 File.lastModified（毫秒）
    exif_datetime: str | None = Form(default=None, max_length=40),  # 手机压缩前读出的 EXIF 拍摄时间
    exif_offset: str | None = Form(default=None, max_length=10),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    s = get_settings()
    names = _names(db)
    existing = db.scalar(select(Attachment).where(Attachment.client_id == client_id))
    if existing is not None:
        if existing.task_id != task_id:
            raise HTTPException(status.HTTP_409_CONFLICT, "client_id already used")
        return _att_out(existing, names)

    task = _get_task(db, task_id)
    _require(db, task, user, "photo")
    if len(task.attachments) >= s.max_photos_per_task:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "too many photos")
    data = await file.read(s.max_upload_mb * 1024 * 1024 + 1)
    if len(data) > s.max_upload_mb * 1024 * 1024:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "file too large")

    now = utcnow()
    mtime = datetime.fromtimestamp(last_modified / 1000, timezone.utc) if last_modified else None
    try:
        p = process_upload(data, _upload_root(), s.tz, mtime, now,
                           client_exif=parse_exif_datetime(exif_datetime, exif_offset, s.tz))
    except InvalidImage:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "not a supported image")

    a = Attachment(
        client_id=client_id, task_id=task.id, filename=(file.filename or "photo")[:255],
        content_type=p.content_type, size=len(data), width=p.width, height=p.height,
        path_original=p.original_rel, path_view=p.view_rel, path_thumb=p.thumb_rel,
        taken_at=p.taken_at.astimezone(timezone.utc), taken_at_source=p.taken_at_source,
        uploaded_by=user.id, uploaded_at=now,
    )
    db.add(a)
    db.flush()
    audit.log(db, user_id=user.id, action="attach", entity="task", entity_id=task.id,
              field="attachments", new=a.filename,
              extra={"attachment_id": a.id, "taken_at": a.taken_at.isoformat(),
                     "taken_at_source": a.taken_at_source, "size": a.size})
    task.updated_by = user.id
    task.updated_at = now
    db.commit()
    return _att_out(a, names)


@router.delete("/attachments/{att_id}", status_code=204)
def delete_attachment(att_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    a = db.get(Attachment, att_id)
    if a is None or a.deleted_at is not None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    task = _get_task(db, a.task_id)
    permissions.require(photo_delete_ok(permissions.who(db, user), task, a), "not your team's task")
    a.deleted_at = utcnow()
    a.deleted_by = user.id
    audit.log(db, user_id=user.id, action="detach", entity="task", entity_id=task.id,
              field="attachments", old=a.filename, extra={"attachment_id": a.id})
    task.updated_by = user.id
    task.updated_at = a.deleted_at
    db.commit()


@router.get("/files/{att_id}/{variant}", include_in_schema=False)
def get_file(att_id: int, variant: str, t: str, db: Session = Depends(get_db)):
    if variant not in ("thumb", "view", "original") or not verify_file_token(t, att_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    a = db.get(Attachment, att_id)
    if a is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    headers = {"Cache-Control": "private, max-age=43200"}
    if variant == "original":
        from .. import storage_service

        path = storage_service.original_file(a)
        if path is None or not path.is_file():  # 原图已归档、归档盘没接上 → 先给浏览图
            path = _upload_root() / a.path_view
            if not path.is_file():
                raise HTTPException(status.HTTP_404_NOT_FOUND)
            return FileResponse(path, media_type="image/jpeg", headers=headers | {"X-Original-Archived": "1"})
        return FileResponse(path, media_type=a.content_type, filename=a.filename, headers=headers)
    path = _upload_root() / (a.path_thumb if variant == "thumb" else a.path_view)
    if not path.is_file():
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    return FileResponse(path, media_type="image/jpeg", headers=headers)
