"""出勤：按月看出勤表、手工修改、Excel 模板与导入、某人某天做了什么。"""

import io
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from fastapi.responses import Response
from openpyxl import Workbook, load_workbook
from openpyxl.styles import Font, PatternFill
from openpyxl.worksheet.datavalidation import DataValidation
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import attendance_service as att, permissions, worker_history
from .. import audit
from ..db import get_db
from ..models import Attendance, Task, Team, User, Worker, utcnow
from ..schemas import TaskOut, WorkerOut
from ..security import get_current_user, require_admin
from .tasks import tasks_out

router = APIRouter(prefix="/api", tags=["attendance"])

MAX_DAYS = 62


class Cell(BaseModel):
    status: str | None
    shift_kind: str | None
    team_id: int | None
    source: str
    note: str = ""


class AttendanceGrid(BaseModel):
    days: list[date]
    workers: list[WorkerOut]
    guest_ids: list[int] = []  # 其他班组来顶班 / 支援的人
    cells: dict[int, dict[date, Cell]]


class AttendanceBatch(BaseModel):
    worker_ids: list[int] = Field(min_length=1, max_length=100)
    start: date
    end: date
    status: str
    shift_kind: str | None = None
    team_id: int | None = None
    note: str = Field(default="", max_length=200)


class AttendanceSwap(BaseModel):
    day: date
    worker_a: int
    worker_b: int
    note: str = Field(default="", max_length=200)


class AttendanceSet(BaseModel):
    worker_id: int
    day: date
    status: str  # present / leave / sick / absent / off / default（恢复默认，删掉例外记录）
    shift_kind: str | None = None
    team_id: int | None = None
    note: str = Field(default="", max_length=200)


class ImportError_(BaseModel):
    row: int
    message: str


class ImportOut(BaseModel):
    imported: int
    errors: list[ImportError_]


class PersonDay(BaseModel):
    worker: WorkerOut
    day: date
    attendance: Cell
    tasks: list[TaskOut]


def _workers(db: Session, team_id: int | None, include_inactive: bool = False) -> list[Worker]:
    q = select(Worker).order_by(Worker.team_id, Worker.name)
    if team_id:
        q = q.where(Worker.team_id == team_id)
    if not include_inactive:
        q = q.where(Worker.is_active.is_(True))
    return list(db.scalars(q))


@router.get("/attendance", response_model=AttendanceGrid)
def grid(start: date, end: date, team_id: int | None = None, db: Session = Depends(get_db),
         _: User = Depends(get_current_user)):
    if end < start or (end - start).days >= MAX_DAYS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"range must be 1..{MAX_DAYS} days")
    # 指定班组时：这段时间里属于过这个班组的人（换过班组的按变更记录，以前的出勤不变）
    workers = worker_history.members(db, team_id, start, end) if team_id else _workers(db, None)
    guests: list[Worker] = []
    if team_id:
        # 这段时间里来这个班组顶班的其他班组员工，也显示出来
        gids = db.scalars(select(Attendance.worker_id).where(
            Attendance.team_id == team_id, Attendance.status == "present",
            Attendance.day >= start, Attendance.day <= end).distinct()).all()
        own = {w.id for w in workers}
        guests = [w for w in db.scalars(select(Worker).where(Worker.id.in_(gids))) if w.id not in own]
        guests.sort(key=lambda w: (w.team_id or 999, w.name))
    eff = att.effective(db, workers + guests, start, end)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    return AttendanceGrid(
        days=days, workers=[WorkerOut.model_validate(w) for w in workers + guests],
        guest_ids=[w.id for w in guests],
        cells={wid: {d: Cell(**vars(c)) for d, c in row.items()} for wid, row in eff.items()},
    )


def _apply(db: Session, worker: Worker, day: date, status_: str, shift_kind: str | None, team_id: int | None,
           note: str, source: str, user_id: int) -> None:
    existing = db.scalar(select(Attendance).where(Attendance.worker_id == worker.id, Attendance.day == day))
    eid = f"{worker.id}:{day}"
    if status_ == "default":
        if existing is not None:
            audit.log(db, user_id=user_id, action="delete", entity="attendance", entity_id=eid,
                      old={"status": existing.status, "shift_kind": existing.shift_kind, "note": existing.note})
            db.delete(existing)
        return
    new = {"status": status_, "shift_kind": shift_kind if status_ == "present" else None,
           "team_id": team_id if status_ == "present" else None, "note": note.strip()}
    if existing is None:
        db.add(Attendance(worker_id=worker.id, day=day, source=source, updated_by=user_id,
                          updated_at=utcnow(), **new))
        audit.log(db, user_id=user_id, action="create", entity="attendance", entity_id=eid,
                  new=new | {"source": source})
    elif audit.log_changes(db, existing, new | {"source": source}, user_id=user_id, entity="attendance",
                           entity_id=eid):
        existing.updated_by = user_id
        existing.updated_at = utcnow()


@router.put("/attendance", response_model=Cell)
def set_attendance(body: AttendanceSet, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    w = db.get(Worker, body.worker_id)
    if w is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    if not permissions.who(db, user).team_ok("attendance.edit", w.team_id):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your team's worker")
    _validate(db, body.status, body.shift_kind, body.team_id)
    _apply(db, w, body.day, body.status, body.shift_kind, body.team_id, body.note, "manual", user.id)
    db.commit()
    c = att.effective(db, [w], body.day, body.day)[w.id][body.day]
    return Cell(**vars(c))


def _validate(db: Session, status_: str, shift_kind: str | None, team_id: int | None) -> None:
    if status_ not in (*att.STATUSES, "default"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "bad status")
    if shift_kind not in (None, "day", "middle", "night"):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "bad shift_kind")
    if team_id is not None and db.get(Team, team_id) is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "team not found")


@router.put("/attendance/batch", response_model=dict)
def set_batch(body: AttendanceBatch, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """批量设置：多人 × 连续多天。典型用法：周末临时安排几个人去顶某个班组的夜班。

    班长可以改本班组的人；也可以把其他班组的人安排来「本班组」上班（出勤 + 顶本班组）。
    """
    if body.end < body.start or (body.end - body.start).days >= 31:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "range must be 1..31 days")
    _validate(db, body.status, body.shift_kind, body.team_id)
    workers = [db.get(Worker, i) for i in dict.fromkeys(body.worker_ids)]
    if any(w is None for w in workers):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "unknown worker")
    who = permissions.who(db, user)
    # 本班组的人可以改；别的班组的人只能安排来「本班组」上班（顶班 / 支援）
    helping_me = body.status == "present" and body.team_id is not None and who.team_ok("attendance.edit", body.team_id)
    if not all(who.team_ok("attendance.edit", w.team_id) or helping_me for w in workers):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "not your team's worker")
    n = 0
    d = body.start
    while d <= body.end:
        for w in workers:
            _apply(db, w, d, body.status, body.shift_kind, body.team_id, body.note, "manual", user.id)
            n += 1
        d += timedelta(days=1)
    audit.log(db, user_id=user.id, action="batch", entity="attendance", entity_id=f"{body.start}~{body.end}",
              new=body.model_dump(mode="json"))
    db.commit()
    return {"updated": n}


@router.post("/attendance/swap", response_model=dict)
def swap(body: AttendanceSwap, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    """两人互换某一天的班：A 上 B 原来的班，B 上 A 原来的班（含休息）。"""
    a, b = db.get(Worker, body.worker_a), db.get(Worker, body.worker_b)
    if a is None or b is None or a.id == b.id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "need two different workers")
    who = permissions.who(db, user)
    if not (who.team_ok("attendance.edit", a.team_id) or who.team_ok("attendance.edit", b.team_id)):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "neither worker is in your team")
    eff = att.effective(db, [a, b], body.day, body.day)
    ea, eb = eff[a.id][body.day], eff[b.id][body.day]
    if (ea.status, ea.shift_kind, ea.team_id) == (eb.status, eb.shift_kind, eb.team_id):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "both have the same shift that day")
    note = body.note.strip() or f"swap {a.name} ⇄ {b.name}"
    tl = worker_history.Timelines(db, [a, b])
    for w, other in ((a, eb), (b, ea)):
        if other.status is None:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "worker without team cannot be swapped")
        mine = tl.on(w.id, body.day).team_id  # 这个人当天所属的班组
        team = other.team_id if other.status == "present" and other.team_id != mine else None
        _apply(db, w, body.day, other.status, other.shift_kind, team, note, "manual", user.id)
    audit.log(db, user_id=user.id, action="swap", entity="attendance", entity_id=f"{a.id}:{b.id}:{body.day}",
              new={"day": body.day, "a": a.name, "b": b.name, "note": note})
    db.commit()
    eff = att.effective(db, [a, b], body.day, body.day)
    return {str(w.id): vars(eff[w.id][body.day]) for w in (a, b)}


# ---------------- Excel 模板与导入 ----------------
TEMPLATE_HEADERS = ["日期 Datum Date", "工号 Matični br. No.", "姓名 Ime Name", "状态 Status", "班次 Smena Shift",
                    "备注 Napomena Note"]


@router.get("/attendance/template")
def template(_: User = Depends(get_current_user)):
    wb = Workbook()
    ws = wb.active
    ws.title = "attendance"
    ws.append(TEMPLATE_HEADERS)
    for c in ws[1]:
        c.font = Font(bold=True)
        c.fill = PatternFill("solid", fgColor="DDEBF7")
    ws.append([date.today(), "", "Petar Petrović", "请假", "", "年假"])
    ws.append([date.today(), "", "张伟", "出勤", "夜班", "顶 3 班夜班"])
    for col, width in zip("ABCDEF", (14, 14, 20, 12, 12, 30)):
        ws.column_dimensions[col].width = width
    for r in (2, 3):
        ws.cell(r, 1).number_format = "yyyy-mm-dd"
    dv = DataValidation(type="list", formula1='"出勤,请假,病假,缺勤,休息"', allow_blank=False)
    ws.add_data_validation(dv)
    dv.add("D2:D2000")
    help_ = wb.create_sheet("说明 Uputstvo Help")
    for line in [
        "只需填写和排班不一样的情况（请假、病假、缺勤、调班/加班）；没填的人按排班默认出勤。",
        "Popunite samo odstupanja od rasporeda (odsustvo, bolovanje, izostanak, zamena smene); ostali se računaju kao prisutni po rasporedu.",
        "Only fill in exceptions to the schedule (leave, sick, absent, shift swap); everyone else counts as present per the schedule.",
        "",
        "日期：2026-11-21 或 21.11.2026；夜班算在开始那天 / Noćna smena se računa na dan početka / Night shift counts on its start date",
        "工号或姓名至少填一个，优先按工号匹配 / Matični broj ili ime / Employee no. or name",
        "状态 Status：出勤 / 请假 / 病假 / 缺勤 / 休息；prisutan / odsustvo / bolovanje / izostanak / slobodan；present / leave / sick / absent / off",
        "班次 Shift（只在出勤且和本班组排班不同时填 / samo za zamenu smene / only for swaps）：白班/中班/夜班；prva/druga/treća；day/middle/night",
    ]:
        help_.append([line])
    help_.column_dimensions["A"].width = 120
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": 'attachment; filename="attendance_template.xlsx"'})


def _parse_day(v) -> date | None:
    if isinstance(v, datetime):
        return v.date()
    if isinstance(v, date):
        return v
    if v is None:
        return None
    s = str(v).strip().rstrip(".")
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%Y/%m/%d", "%d/%m/%Y", "%Y.%m.%d"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


@router.post("/attendance/import", response_model=ImportOut)
async def import_attendance(file: UploadFile = File(...), db: Session = Depends(get_db),
                            admin: User = Depends(require_admin)):
    """按模板导入。先全部校验，有任何一行出错就一行都不导入，返回错误清单。"""
    data = await file.read(10 * 1024 * 1024)
    try:
        ws = load_workbook(io.BytesIO(data), data_only=True).worksheets[0]
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "not an .xlsx file")

    workers = list(db.scalars(select(Worker)))
    by_no = {w.employee_no.strip(): w for w in workers if w.employee_no}
    by_name: dict[str, list[Worker]] = {}
    for w in workers:
        by_name.setdefault(w.name.strip().lower(), []).append(w)

    rows, errors = [], []
    for i, r in enumerate(ws.iter_rows(min_row=2, values_only=True), start=2):
        r = list(r) + [None] * 6
        if all(v is None or str(v).strip() == "" for v in r[:6]):
            continue
        d, no, name, st, sh, note = r[:6]
        day = _parse_day(d)
        if day is None:
            errors.append(ImportError_(row=i, message=f"日期无法识别 / bad date: {d!r}"))
            continue
        w = by_no.get(str(no).strip()) if no not in (None, "") else None
        if w is None and name:
            cands = by_name.get(str(name).strip().lower(), [])
            if len(cands) > 1:
                errors.append(ImportError_(row=i, message=f"重名，请填工号 / duplicate name: {name}"))
                continue
            w = cands[0] if cands else None
        if w is None:
            errors.append(ImportError_(row=i, message=f"找不到员工 / unknown worker: {no or ''} {name or ''}"))
            continue
        status_ = att.parse_status(st)
        if status_ is None:
            errors.append(ImportError_(row=i, message=f"状态无法识别 / bad status: {st!r}"))
            continue
        shift = att.parse_shift(sh)
        if shift == "invalid":
            errors.append(ImportError_(row=i, message=f"班次无法识别 / bad shift: {sh!r}"))
            continue
        rows.append((w, day, status_, shift, str(note or "")[:200]))

    seen = {}
    for idx, (w, day, *_rest) in enumerate(rows):
        if (w.id, day) in seen:
            errors.append(ImportError_(row=0, message=f"同一人同一天出现两次 / duplicate: {w.name} {day}"))
        seen[(w.id, day)] = idx
    if errors:
        return ImportOut(imported=0, errors=sorted(errors, key=lambda e: e.row))

    for w, day, status_, shift, note in rows:
        _apply(db, w, day, status_, shift, None, note, "import", admin.id)
    audit.log(db, user_id=admin.id, action="import", entity="attendance", entity_id=file.filename or "xlsx",
              new={"rows": len(rows)})
    db.commit()
    return ImportOut(imported=len(rows), errors=[])


# ---------------- 某人某天 ----------------
@router.get("/workers/{worker_id}/day", response_model=PersonDay)
def person_day(worker_id: int, day: date, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    w = db.get(Worker, worker_id)
    if w is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND)
    c = att.effective(db, [w], day, day)[w.id][day]
    tasks = db.scalars(select(Task).options(selectinload(Task.workers), selectinload(Task.attachments))
                       .where(Task.workers.any(Worker.id == w.id), Task.shift_date == day)
                       .order_by(Task.created_at)).all()
    return PersonDay(worker=WorkerOut.model_validate(w), day=day, attendance=Cell(**vars(c)),
                     tasks=tasks_out(db, list(tasks), user))
