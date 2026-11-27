"""工厂的出勤月表（和人事用的表一样的格式）：下载模板、导出出勤都用它，导入也认它（routers/attendance.py）。

  第 1 行：Year | | 2026 | | | 填表说明（合并到第 2 行）
  第 2 行：Month | | 12
  第 3 行：Day Date | Sap No. | 每天的日期（公式：按 C1 年、C2 月算，改年月日期跟着变）
  第 4 行：Name | | 星期（公式 = 上面的日期，显示成 Mon、Tue……）
  第 5 行起：姓名 | Sap No.（= 名册工号）| 每天一格，按班组分块、中间空一行
格子：1 / 2 / 3 = 白 / 中 / 夜（夜班记在下班那天），/ = 休息，请假等写缩写（导入时存下来的原样写回，
手工改的：请假 AL、病假 SL、缺勤 RW）。
"""

import calendar
from datetime import date

from openpyxl.styles import Alignment, Font, PatternFill
from openpyxl.utils import get_column_letter

from .attendance_service import DayAttendance

NOTE = ("Note: please follow the following rules to fill the table: \n"
        "Work: First shift=1-8h, 1-10h, 1-12h; Second shift=2-8h, 2-10h, 2-12h; Third shift=3-8h, 3-10h, 3-12h "
        "(8h/10h/12h shift); \n"
        "Abesence: State holiday=PH; Religion holiday/SLAVA=RH; Annual leave=AL; Sick leave=SL; Sick leave for work "
        "injury=SLI; Sick leave for pregenancy=SLP; Paid leave court=PLC; Paid leave military=PLM; Paid leave exam=PLE; "
        "Paid leave death=PLD; Paid  leave blood donation=PLBD; Paid leave wedding=PLW; Paid leave child birth=PLCB; "
        "Unpaid leave=UL; Earned hours=EH; Spent hours=SH (used previous earned hours for rest); Business trip=BT; "
        "Removal from work=RW.")
SHIFT_CODE = {"day": "1", "middle": "2", "night": "3"}
STATUS_CODE = {"off": "/", "leave": "AL", "sick": "SL", "absent": "RW"}  # 没有原始缩写时（手工改的）
FILLS = {"leave": "FFF2CC", "sick": "FCE4D6", "absent": "F8CBAD"}
FIRST = 3  # 第 1 天在 C 列
COLS = 31


def code(a: DayAttendance | None) -> str:
    """一格写什么。"""
    if a is None or a.status is None:
        return ""
    if a.code:
        return a.code
    if a.status == "present":
        return SHIFT_CODE.get(a.shift_kind or "", "")
    return STATUS_CODE.get(a.status, "")


def _sap(no: str | None):
    no = (no or "").strip()
    return int(no) if no.isdigit() and len(no) < 16 else no


def write_month(ws, year: int, month: int, groups: list[list], eff: dict) -> None:
    """把一个月写进 ws。groups = 按班组分好的员工列表（每组之间空一行）；eff = {员工 id: {日期: 出勤}}，
    没有的日子（例如导出的时间段以外）留空。"""
    ndays = calendar.monthrange(year, month)[1]
    ws["A1"], ws["C1"], ws["A2"], ws["C2"] = "Year", year, "Month", month
    ws["F1"] = NOTE
    ws.merge_cells("A1:B1")
    ws.merge_cells("A2:B2")
    ws.merge_cells("F1:AF2")  # 和工厂的表一样
    ws["F1"].alignment = Alignment(wrap_text=True, vertical="top")
    ws.row_dimensions[1].height = 60
    ws.row_dimensions[2].height = 60
    ws["A3"], ws["B3"], ws["A4"] = "Day          Date", "Sap No.", "Name"
    ws.merge_cells("B3:B4")
    bold = Font(bold=True)
    for c in ("A1", "A2", "A3", "B3", "A4"):
        ws[c].font = bold
    for k in range(COLS):
        col = get_column_letter(FIRST + k)
        ref = get_column_letter(k + 1)
        d3 = ws.cell(3, FIRST + k, f'=IF(MONTH(DATE($C$1,$C$2,COLUMN({ref}1)))=$C$2,DATE($C$1,$C$2,COLUMN({ref}1)),"")')
        d3.number_format = "d"
        d4 = ws.cell(4, FIRST + k, f"={col}3")
        d4.number_format = "ddd"
        for c in (d3, d4):
            c.alignment = Alignment(horizontal="center")
            c.font = bold
        ws.column_dimensions[col].width = 5.6
    ws.column_dimensions["A"].width = 20
    ws.column_dimensions["B"].width = 11
    r = 5
    center = Alignment(horizontal="center")
    for gi, workers in enumerate(groups):
        if gi:
            r += 1  # 班组之间空一行
        for w in workers:
            ws.cell(r, 1, w.name)
            ws.cell(r, 2, _sap(w.employee_no))
            row = eff.get(w.id, {})
            for i in range(ndays):
                a = row.get(date(year, month, i + 1))
                c = ws.cell(r, FIRST + i, code(a))
                c.alignment = center
                if a is not None and a.status in FILLS:
                    c.fill = PatternFill("solid", fgColor=FILLS[a.status])
                if a is not None and a.source not in ("default",):
                    c.font = Font(italic=True, bold=True)
            r += 1
    ws.freeze_panes = "C5"


def months_between(start: date, end: date) -> list[tuple[int, int]]:
    out, y, m = [], start.year, start.month
    while (y, m) <= (end.year, end.month):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def group_by_team(workers: list, teams: list) -> list[list]:
    """按班组的顺序分块（teams 已排好序），没有班组的放最后。"""
    order = {t.id: i for i, t in enumerate(teams)}
    groups: dict = {}
    for w in workers:
        groups.setdefault(w.team_id if w.team_id in order else None, []).append(w)
    keys = sorted((k for k in groups if k is not None), key=lambda k: order[k]) + ([None] if None in groups else [])
    return [sorted(groups[k], key=lambda w: w.name) for k in keys]
