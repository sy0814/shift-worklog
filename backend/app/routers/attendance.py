"""出勤：按月看出勤表、手工修改、Excel 模板与导入、某人某天做了什么。"""

import io
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
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
from ..departments import get_dept
from .tasks import tasks_out

router = APIRouter(prefix="/api", tags=["attendance"])

MAX_DAYS = 62


class Cell(BaseModel):
    status: str | None
    shift_kind: str | None
    team_id: int | None
    source: str
    note: str = ""
    hours: str | None = None  # 自定义上班时间
    code: str | None = None  # 出勤月表里的原始写法（AL、SL、BT……）


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
    # 出勤月表：几个人、几天、和排班不一样记下的例外（imported）、和排班一样而清掉的旧例外
    month: str | None = None
    people: int = 0
    days: int = 0
    cleared: int = 0


class PersonDay(BaseModel):
    worker: WorkerOut
    day: date
    attendance: Cell
    tasks: list[TaskOut]


def _workers(db: Session, team_id: int | None, include_inactive: bool = False, dept: int | None = None) -> list[Worker]:
    q = select(Worker).order_by(Worker.team_id, Worker.name)
    if team_id:
        q = q.where(Worker.team_id == team_id)
    elif dept is not None:
        q = q.where(Worker.department_id == dept)
    if not include_inactive:
        q = q.where(Worker.is_active.is_(True))
    return list(db.scalars(q))


@router.get("/attendance", response_model=AttendanceGrid)
def grid(start: date, end: date, team_id: int | None = None, db: Session = Depends(get_db),
         _: User = Depends(get_current_user), dept: int | None = Depends(get_dept)):
    if end < start or (end - start).days >= MAX_DAYS:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"range must be 1..{MAX_DAYS} days")
    # 指定班组时：这段时间里属于过这个班组的人（换过班组的按变更记录，以前的出勤不变）；不指定 = 当前车间的人
    workers = worker_history.members(db, team_id, start, end) if team_id else _workers(db, None, dept=dept)
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
           note: str, source: str, user_id: int, code: str | None = None) -> bool:
    """写一条例外（status_ = default：删掉例外，恢复按排班）。返回有没有改动。"""
    existing = db.scalar(select(Attendance).where(Attendance.worker_id == worker.id, Attendance.day == day))
    eid = f"{worker.id}:{day}"
    if status_ == "default":
        if existing is not None:
            audit.log(db, user_id=user_id, action="delete", entity="attendance", entity_id=eid,
                      old={"status": existing.status, "shift_kind": existing.shift_kind, "note": existing.note})
            db.delete(existing)
            return True
        return False
    new = {"status": status_, "shift_kind": shift_kind if status_ == "present" else None,
           "team_id": team_id if status_ == "present" else None, "note": note.strip(), "code": code}
    if existing is None:
        db.add(Attendance(worker_id=worker.id, day=day, source=source, updated_by=user_id,
                          updated_at=utcnow(), **new))
        audit.log(db, user_id=user_id, action="create", entity="attendance", entity_id=eid,
                  new=new | {"source": source})
        return True
    if audit.log_changes(db, existing, new | {"source": source}, user_id=user_id, entity="attendance",
                         entity_id=eid):
        existing.updated_by = user_id
        existing.updated_at = utcnow()
        return True
    return False


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
@router.get("/attendance/template")
def template(month: str | None = None, team_id: int | None = None, db: Session = Depends(get_db),
             user: User = Depends(get_current_user), dept: int | None = Depends(get_dept)):
    """下载出勤月表（工厂的格式，见 app/attendance_sheet.py）：这个月每个人每天按系统里的出勤填好（排班 + 已有的修改），
    改好请假、调班这些再导入。也就是这个月的出勤导出。能导入的人才能下载（管理员；出勤权限为本车间 / 全厂的人）。"""
    import calendar

    from .. import attendance_sheet as sheet
    from ..schedule_service import local_now

    who = permissions.who(db, user)
    permissions.require(who.scope("attendance.edit") in ("dept", "all"))
    try:
        y, m = (int(x) for x in (month or f"{local_now():%Y-%m}").split("-"))
        start = date(y, m, 1)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "month required (YYYY-MM)")
    end = date(y, m, calendar.monthrange(y, m)[1])
    if team_id:
        workers = [w for w in worker_history.members(db, team_id, start, end) if w.is_active]
    else:
        workers = _workers(db, None, dept=dept)
    teams = list(db.scalars(select(Team).order_by(Team.sort_order, Team.id)))
    wb = Workbook()
    ws = wb.active
    ws.title = f"{m:02d}-{y}"
    sheet.write_month(ws, y, m, sheet.group_by_team(workers, teams), att.effective(db, workers, start, end))
    buf = io.BytesIO()
    wb.save(buf)
    return Response(buf.getvalue(), media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f'attachment; filename="attendance_{y}-{m:02d}.xlsx"'})


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
async def import_attendance(file: UploadFile = File(...), month: str | None = Form(default=None),
                            db: Session = Depends(get_db), admin: User = Depends(get_current_user)):
    """按模板导入，或导入工厂的出勤月表（有「Sap No.」那一列的；month = 页面上选的月份，例如 2026-11）。
    系统管理员：全厂；出勤权限为「本车间」的车间管理员：只能导本车间的人。
    先全部校验，有任何一处出错就一条都不导入，返回错误清单。"""
    who = permissions.who(db, admin)
    scope = who.scope("attendance.edit")
    permissions.require(scope in ("dept", "all"))
    data = await file.read(10 * 1024 * 1024)
    try:
        ws = load_workbook(io.BytesIO(data), data_only=True).worksheets[0]
    except Exception:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "not an .xlsx file")

    wq = select(Worker)
    if scope == "dept":
        wq = wq.where(Worker.department_id == who.dept_id)
    workers = list(db.scalars(wq))
    by_no = {w.employee_no.strip(): w for w in workers if w.employee_no}
    by_name: dict[str, list[Worker]] = {}
    for w in workers:
        by_name.setdefault(w.name.strip().lower(), []).append(w)
    if (sap := _find_sheet_header(ws)) is not None:
        return _import_sheet(db, ws, sap, month, by_no, by_name, admin, file.filename or "xlsx")

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


# ---------------- 工厂出勤月表 ----------------
_WEEKDAYS = {  # 表里第二行的星期（英 / 塞 / 中），Python weekday()：周一 = 0
    **{k: i for i, k in enumerate(("mon", "tue", "wed", "thu", "fri", "sat", "sun"))},
    **{k: i for i, k in enumerate(("pon", "uto", "sre", "čet", "pet", "sub", "ned"))},
    **{k: i for i, k in enumerate(("一", "二", "三", "四", "五", "六", "日"))},
}


def _find_sheet_header(ws) -> tuple[int, int] | None:
    """出勤月表：前 6 行里找「Sap No.」那一格 → (行, 列)，都从 1 开始；不是月表返回 None。"""
    for r in range(1, min(ws.max_row, 6) + 1):
        for c in range(1, min(ws.max_column, 10) + 1):
            v = ws.cell(r, c).value
            if isinstance(v, str) and v.strip().lower().replace(" ", "").startswith("sapno"):
                return r, c
    return None


def _sheet_dates(ws, hr: int, first: int, month: str | None) -> tuple[list[date], str, list[ImportError_]]:
    """月表每一列是哪天。按优先顺序：
    1. 日期那一行本身就是日期（工厂新表用公式算出来的，Excel 存了结果）→ 直接用
    2. 表上面写了 Year / Month（年、月）→ 按列的顺序算
    3. 都没有（老的表）→ 用页面上选的月份按列的顺序算，再用星期那一行核对
    返回 (日期列表, "YYYY-MM", 错误)。"""
    import calendar

    errors: list[ImportError_] = []
    head = []
    for i in range(31):
        v = ws.cell(hr, first + i).value
        if isinstance(v, datetime):
            v = v.date()
        if not isinstance(v, date):
            break
        head.append(v)
    if head:
        ym = f"{head[0]:%Y-%m}"
        if any(f"{d:%Y-%m}" != ym for d in head) or [d.day for d in head] != list(range(1, len(head) + 1)):
            errors.append(ImportError_(row=hr, message="日期那一行不是同一个月从 1 号起连着的日期 / dates must be one month from day 1"))
        return head, ym, errors
    y = m = None
    for r in range(1, hr):
        label = str(ws.cell(r, 1).value or "").strip().lower()
        val = next((ws.cell(r, c).value for c in range(2, 6) if isinstance(ws.cell(r, c).value, (int, float))), None)
        if val is None:
            continue
        if label.startswith(("year", "godina", "年")):
            y = int(val)
        elif label.startswith(("month", "mesec", "月")):
            m = int(val)
    from_sheet = y is not None and m is not None
    if not from_sheet:
        try:
            y, m = (int(x) for x in (month or "").split("-"))
        except ValueError:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "month required (YYYY-MM)")
    if not (1 <= m <= 12 and 2000 <= y <= 2100):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "month required (YYYY-MM)")
    ym = f"{y:04d}-{m:02d}"
    ndays = calendar.monthrange(y, m)[1]
    days = [date(y, m, i + 1) for i in range(ndays)]
    if not from_sheet:  # 星期那一行（文字）核对月份；多出来的列必须是空的
        for i in range(ndays + 3):
            v = ws.cell(hr + 1, first + i).value
            s = str(v).strip().lower()[:3] if v is not None else ""
            if i >= ndays:
                if s:
                    errors.append(ImportError_(row=hr + 1, message=f"表里的天数比 {ym} 的 {ndays} 天多 / more day columns than {ndays}"))
                break
            if not s:
                errors.append(ImportError_(row=hr + 1, message=f"第 {i + 1} 天没有星期，表里的天数比 {ym} 少？ / missing weekday for day {i + 1}"))
                break
            if s in _WEEKDAYS and _WEEKDAYS[s] != days[i].weekday():
                errors.append(ImportError_(row=hr + 1, message=f"第 {i + 1} 天写的是 {v}，可 {days[i]} 是星期{'一二三四五六日'[days[i].weekday()]}，月份选错了？ / weekday mismatch, wrong month?"))
                break
    return days, ym, errors


def _import_sheet(db: Session, ws, sap: tuple[int, int], month: str | None, by_no: dict, by_name: dict,
                  admin: User, filename: str) -> ImportOut:
    """导入出勤月表（工厂的格式：Year / Month、日期行、星期行，一行一个人：姓名、Sap No.、每天一格）。
    人按 Sap No. 对名册工号，没填工号的按姓名（不能重名）。每一格和排班比：一样的不记（以前有例外的清掉），
    不一样的记成例外；空格子不改。"""
    from ..schedule_service import load_schedule
    from ..worker_history import Timelines

    hr, sc = sap
    first = sc + 1  # 第 1 天所在的列
    days, month, errors = _sheet_dates(ws, hr, first, month)
    rows: list[tuple[Worker, list]] = []
    seen: dict[int, int] = {}
    for r in range(hr + 2, ws.max_row + 1):
        no = ws.cell(r, sc).value
        name = ws.cell(r, sc - 1).value if sc > 1 else None
        no = str(int(no)) if isinstance(no, float) and no.is_integer() else str(no or "").strip()
        name = str(name or "").strip()
        if not no and not name:
            continue
        who = f"{name} {no}".strip()
        if no:
            w = by_no.get(no)
            if w is None:
                errors.append(ImportError_(row=r, message=f"工号 {no} 在名册里找不到（先在员工名册里填上工号）/ unknown Sap No. {no}"))
                continue
        else:
            cands = by_name.get(name.lower(), [])
            if len(cands) != 1:
                errors.append(ImportError_(row=r, message=(f"「{name}」重名，请填 Sap No. / duplicate name" if cands else
                                                           f"「{name}」在名册里找不到，请填 Sap No. / unknown name")))
                continue
            w = cands[0]
        if w.id in seen:
            errors.append(ImportError_(row=r, message=f"{who} 出现两次（第 {seen[w.id]} 行）/ duplicate person"))
            continue
        seen[w.id] = r
        cells = []
        for i, d in enumerate(days):
            v = ws.cell(r, first + i).value
            x = att.sheet_cell(v)
            if x == "invalid":
                errors.append(ImportError_(row=r, message=f"{who} {d:%m-%d}：认不出「{v}」/ cannot read {v!r}"))
            cells.append(x)
        rows.append((w, cells))
    if errors:
        return ImportOut(imported=0, errors=sorted(errors, key=lambda e: e.row), month=month)

    sched = load_schedule(db)
    tl = Timelines(db, [w for w, _ in rows])
    written = cleared = 0
    for w, cells in rows:
        for d, x in zip(days, cells):
            if x is None:
                continue
            st, sh, code = x
            base = att.default_for(sched, tl.on(w.id, d), d)
            same = code is None and st == base.status and (st != "present" or sh == base.shift_kind)
            if same:
                cleared += _apply(db, w, d, "default", None, None, "", "import", admin.id)
            else:
                written += _apply(db, w, d, st, sh, None, code or "", "import", admin.id, code=code)
    audit.log(db, user_id=admin.id, action="import", entity="attendance", entity_id=filename,
              new={"month": month, "people": len(rows), "exceptions": written, "cleared": cleared})
    db.commit()
    return ImportOut(imported=written, errors=[], month=month, people=len(rows), days=len(days), cleared=cleared)


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
