"""Excel 导出：按时间段 / 班组 / 人员，三个工作表（任务明细、人员工作量、出勤表），可选中 / 塞 / 英。

时间段按班次日期（夜班归属开始那天）。工时 = 完成时间 − 开始时间；一条任务有多名参与人员时，
每人都计这条任务的全部工时（不按人数平摊）。
"""

import io
from datetime import date, datetime, timedelta, timezone
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import Response
from openpyxl import Workbook
from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .. import attendance_service as att
from .. import audit
from ..config import get_settings
from ..db import get_db
from ..models import Task, TaskHandover, Team, User, Worker
from ..schedule_service import load_schedule
from ..security import get_current_user

router = APIRouter(prefix="/api", tags=["export"])

L = {
    "zh": {
        "sheet_tasks": "任务明细", "sheet_load": "人员工作量", "sheet_att": "出勤",
        "tasks": ["编号", "班次日期", "班次", "班组", "状态", "工作内容", "原文", "遗留问题", "带队人员", "参与人员", "开始时间",
                  "完成时间", "工时(小时)", "发布人", "最后修改人", "完成确认人", "移交", "废弃原因", "图片数", "已移交次数"],
        "load": ["姓名", "工号", "班组", "排班班次", "实际出勤", "请假", "病假", "缺勤", "参与任务", "已完成", "未完成",
                 "任务工时合计(小时)"],
        "att": ["姓名", "工号", "班组"],
        "status": {"not_started": "未开始", "in_progress": "进行中", "done": "已完成", "handed_over": "已移交", "discarded": "已废弃"},
        "shift": {"day": "白班", "middle": "中班", "night": "夜班", "off": "休息"},
        "code": {"day": "白", "middle": "中", "night": "夜", "off": "休", "leave": "假", "sick": "病", "absent": "缺", None: ""},
        "from": "来自", "to": "交给", "title": "工作记录导出", "range": "时间段", "note_hours": "多人参与的任务每人都计全部工时",
        "legend": "白/中/夜 = 出勤班次，休 = 休息，假 = 请假，病 = 病假，缺 = 缺勤；斜体 = 手工修改或导入",
    },
    "sr": {
        "sheet_tasks": "Zadaci", "sheet_load": "Opterećenje", "sheet_att": "Prisustvo",
        "tasks": ["Br.", "Datum smene", "Smena", "Ekipa", "Status", "Opis posla", "Original", "Preostali problemi",
                  "Vođa ekipe", "Učesnici", "Početak", "Završetak", "Sati", "Uneo", "Poslednja izmena", "Potvrdio", "Predaja",
                  "Razlog odbacivanja", "Slike", "Broj predaja"],
        "load": ["Ime", "Matični br.", "Ekipa", "Smene po rasporedu", "Prisutan", "Odsustvo", "Bolovanje", "Izostanak",
                 "Zadaci", "Završeno", "Nezavršeno", "Ukupno sati"],
        "att": ["Ime", "Matični br.", "Ekipa"],
        "status": {"not_started": "Nije započeto", "in_progress": "U toku", "done": "Završeno", "handed_over": "Predato", "discarded": "Odbačeno"},
        "shift": {"day": "Prva", "middle": "Druga", "night": "Treća", "off": "Slobodno"},
        "code": {"day": "P", "middle": "D", "night": "T", "off": "S", "leave": "O", "sick": "B", "absent": "I", None: ""},
        "from": "od", "to": "za", "title": "Izvoz radnog dnevnika", "range": "Period", "note_hours": "Za zadatke sa više učesnika svakom se računaju svi sati",
        "legend": "P/D/T = prva/druga/treća smena, S = slobodno, O = odsustvo, B = bolovanje, I = izostanak; kurziv = ručno ili uvezeno",
    },
    "en": {
        "sheet_tasks": "Tasks", "sheet_load": "Workload", "sheet_att": "Attendance",
        "tasks": ["No.", "Shift date", "Shift", "Team", "Status", "Work", "Original", "Open issues", "Lead", "Workers", "Start",
                  "Finish", "Hours", "Posted by", "Last edited by", "Confirmed by", "Handover", "Discard reason", "Photos",
                  "Handovers"],
        "load": ["Name", "Employee no.", "Team", "Scheduled shifts", "Present", "Leave", "Sick", "Absent", "Tasks",
                 "Done", "Open", "Task hours"],
        "att": ["Name", "Employee no.", "Team"],
        "status": {"not_started": "Not started", "in_progress": "In progress", "done": "Done", "handed_over": "Handed over", "discarded": "Discarded"},
        "shift": {"day": "Day", "middle": "Middle", "night": "Night", "off": "Off"},
        "code": {"day": "D", "middle": "M", "night": "N", "off": "O", "leave": "L", "sick": "S", "absent": "A", None: ""},
        "from": "from", "to": "to", "title": "Work log export", "range": "Period", "note_hours": "Tasks with several workers count full hours for each",
        "legend": "D/M/N = day/middle/night shift, O = off, L = leave, S = sick, A = absent; italic = edited or imported",
    },
}

HEAD = PatternFill("solid", fgColor="DDEBF7")
FILLS = {"leave": "FFF2CC", "sick": "FCE4D6", "absent": "F8CBAD", "off": "EDEDED"}


def _local(d: datetime | None) -> datetime | None:
    if d is None:
        return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=timezone.utc)
    return d.astimezone(get_settings().tz).replace(tzinfo=None)


def _text(task: Task, field: str, src_col: str, lang: str) -> tuple[str, str]:
    """返回 (导出语言的文字, 原文)。没有该语言译文时用原文。"""
    src = getattr(task, src_col)
    orig = getattr(task, f"{field}_{src}") if src else None
    return getattr(task, f"{field}_{lang}") or orig or "", orig or ""


def _hours(t: Task) -> float | None:
    if t.start_at and t.end_at:
        return round((_local(t.end_at) - _local(t.start_at)).total_seconds() / 3600, 2)
    return None


def _header(ws, row: list[str]) -> None:
    ws.append(row)
    for c in ws[ws.max_row]:
        c.font = Font(bold=True)
        c.fill = HEAD
        c.alignment = Alignment(vertical="center", wrap_text=True)


def build_workbook(db: Session, start: date, end: date, team_id: int | None, worker_id: int | None,
                   lang: str) -> Workbook:
    T = L[lang]
    teams = {t.id: t for t in db.scalars(select(Team))}
    tname = lambda tid: getattr(teams[tid], f"name_{lang}") if tid in teams else ""
    names = dict(db.execute(select(User.id, User.full_name)).all())

    q = select(Task).options(selectinload(Task.workers), selectinload(Task.attachments)) \
        .where(Task.shift_date >= start, Task.shift_date <= end)
    if team_id:
        q = q.where(Task.team_id == team_id)
    if worker_id:
        q = q.where(Task.workers.any(Worker.id == worker_id))
    tasks = list(db.scalars(q.order_by(Task.shift_date, Task.created_at)))
    ids = [t.id for t in tasks]
    hos = list(db.scalars(select(TaskHandover).where(
        (TaskHandover.from_task_id.in_(ids)) | (TaskHandover.to_task_id.in_(ids))))) if ids else []
    ho_out = {h.from_task_id: h for h in hos}
    ho_in = {h.to_task_id: h for h in hos}

    wb = Workbook()
    # ---- 任务明细 ----
    ws = wb.active
    ws.title = T["sheet_tasks"]
    _header(ws, T["tasks"])
    for t in tasks:
        content, orig = _text(t, "content", "source_lang", lang)
        leftover, _ = _text(t, "leftover", "leftover_source_lang", lang)
        reason, _ = _text(t, "discard_reason", "discard_reason_lang", lang)
        ho = []
        if t.id in ho_in:
            ho.append(f"{T['from']} {tname(ho_in[t.id].from_team_id)} (#{ho_in[t.id].from_task_id})")
        if t.id in ho_out:
            ho.append(f"{T['to']} {tname(ho_out[t.id].to_team_id)} (#{ho_out[t.id].to_task_id})")
        ws.append([
            t.id, t.shift_date, T["shift"].get(t.shift_kind, t.shift_kind), tname(t.team_id),
            T["status"].get(t.status, t.status), content, orig if orig != content else "", leftover,
            next((w.name for w in t.workers if w.id == t.lead_worker_id), ""),
            ", ".join(w.name for w in t.workers if w.id != t.lead_worker_id),
            _local(t.start_at), _local(t.end_at), _hours(t),
            names.get(t.created_by, ""), names.get(t.updated_by, ""), names.get(t.confirmed_by, "") if t.confirmed_by else "",
            "; ".join(ho), reason, len(t.attachments), t.handover_count,
        ])
    widths = [7, 12, 8, 10, 10, 50, 40, 35, 14, 25, 16, 16, 9, 12, 12, 12, 22, 30, 7, 8]
    for i, wdt in enumerate(widths, start=1):
        ws.column_dimensions[get_column_letter(i)].width = wdt
    for row in ws.iter_rows(min_row=2):
        row[1].number_format = "yyyy-mm-dd"
        row[10].number_format = row[11].number_format = "yyyy-mm-dd hh:mm"
        for c in (row[5], row[6], row[7], row[17]):
            c.alignment = Alignment(wrap_text=True, vertical="top")
    ws.freeze_panes = "B2"
    ws.auto_filter.ref = ws.dimensions

    # ---- 人员：范围内的员工 ----
    if worker_id:
        workers = [w for w in [db.get(Worker, worker_id)] if w]
    else:
        q = select(Worker).where(Worker.is_active.is_(True))
        if team_id:
            q = q.where(Worker.team_id == team_id)
        workers = list(db.scalars(q))
        seen = {w.id for w in workers}
        for t in tasks:  # 来帮忙的其他班组员工也算进来
            for w in t.workers:
                if w.id not in seen and not team_id:
                    workers.append(w)
                    seen.add(w.id)
    workers.sort(key=lambda w: (w.team_id or 999, w.name))
    eff = att.effective(db, workers, start, end)
    sched = load_schedule(db)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]

    # ---- 人员工作量 ----
    ws2 = wb.create_sheet(T["sheet_load"])
    _header(ws2, T["load"])
    for w in workers:
        sched_n = sum(1 for d in days if att.default_for(sched, w, d).status == "present")  # 按排班应上的班次
        present = sum(1 for a in eff[w.id].values() if a.status == "present")
        mine = [t for t in tasks if any(x.id == w.id for x in t.workers)]
        hours = sum(h for t in mine if (h := _hours(t)) is not None)
        ws2.append([
            w.name, w.employee_no or "", tname(w.team_id), sched_n, present,
            sum(1 for a in eff[w.id].values() if a.status == "leave"),
            sum(1 for a in eff[w.id].values() if a.status == "sick"),
            sum(1 for a in eff[w.id].values() if a.status == "absent"),
            len(mine), sum(1 for t in mine if t.status == "done"),
            sum(1 for t in mine if t.status in ("not_started", "in_progress")), round(hours, 2),
        ])
    for i, wdt in enumerate([20, 12, 10, 10, 10, 8, 8, 8, 9, 9, 9, 14], start=1):
        ws2.column_dimensions[get_column_letter(i)].width = wdt
    ws2.append([])
    ws2.append([T["note_hours"]])
    ws2.freeze_panes = "B2"

    # ---- 出勤表 ----
    ws3 = wb.create_sheet(T["sheet_att"])
    _header(ws3, T["att"] + [d.strftime("%m-%d") for d in days])
    for w in workers:
        cells = []
        for d in days:
            a = eff[w.id][d]
            key = a.shift_kind if a.status == "present" else a.status
            cells.append(T["code"].get(key, ""))
        ws3.append([w.name, w.employee_no or "", tname(w.team_id)] + cells)
        r = ws3.max_row
        for j, d in enumerate(days):
            a = eff[w.id][d]
            c = ws3.cell(r, 4 + j)
            c.alignment = Alignment(horizontal="center")
            if a.status in FILLS:
                c.fill = PatternFill("solid", fgColor=FILLS[a.status])
            if a.source != "default":
                c.font = Font(italic=True, bold=True)
    ws3.column_dimensions["A"].width = 20
    for j in range(len(days)):
        ws3.column_dimensions[get_column_letter(4 + j)].width = 5
    ws3.freeze_panes = "D2"
    ws3.append([])
    ws3.append([T["legend"]])
    return wb


@router.get("/export/tasks")
def export_tasks(
    start: date,
    end: date,
    team_id: int | None = None,
    worker_id: int | None = None,
    lang: str = Query(default="zh", pattern="^(zh|sr|en)$"),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if end < start or (end - start).days > 366:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "range must be 0..366 days")
    if user.role != "admin":
        # 班长只能导出本班组
        if team_id not in (None, user.team_id):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "own team only")
        team_id = user.team_id
    wb = build_workbook(db, start, end, team_id, worker_id, lang)
    audit.log(db, user_id=user.id, action="export", entity="export", entity_id="tasks",
              new={"start": start, "end": end, "team_id": team_id, "worker_id": worker_id, "lang": lang})
    db.commit()
    buf = io.BytesIO()
    wb.save(buf)
    fname = f"worklog_{start}_{end}.xlsx"
    return Response(buf.getvalue(),
                    media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                    headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(fname)}"})
