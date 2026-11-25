"""排班场景表：逐条读 docs/SCHEDULE_SCENARIOS.md 的「设置」和表格，检查排班引擎 + 出勤计算的结果。

不用数据库：直接用业务代码里的同一批纯函数（Schedule、attendance_service.resolve、
schedule_service.vote_member_shifts），所以表格写的就是系统真实的行为。
「原因」列和页面「为什么？」里标黄的步骤一致（同一份 trace）。
"""

import re
from bisect import bisect_right
from dataclasses import dataclass, replace
from datetime import date, datetime, timedelta
from pathlib import Path

import pytest

from app import attendance_service as att
from app.schedule_service import vote_member_shifts
from app.shifts import OFF, Cycle, Schedule, TeamInfo, day_team, rotating
from app.worker_history import EPOCH, Entry

DOC = Path(__file__).resolve().parents[2] / "docs" / "SCHEDULE_SCENARIOS.md"

KIND = {"白": "day", "中": "middle", "夜": "night", "休": "off"}
KIND_NAME = {v: k for k, v in KIND.items()}
STATUS = {"出勤": "present", "请假": "leave", "病假": "sick", "缺勤": "absent", "休息": "off"}
STATUS_NAME = {"leave": "请假", "sick": "病假", "absent": "缺勤", "off": "休"}
# 和前端 WhyPanel.vue 的 STRONG（标黄）一致
REASON = {"holiday": "节假日", "workday": "调休上班", "inactive": "不在有效期", "team_override": "班组调班",
          "member_shift": "按人员", "personal_cycle": "个人循环", "attendance": "出勤记录", "cover": "顶班"}
NONE = "—"


@dataclass
class Rec:  # 出勤例外记录（resolve 用到的字段）
    status: str
    shift_kind: str | None = None
    team_id: int | None = None
    source: str = "manual"
    note: str = ""
    updated_by: int | None = None
    updated_at: datetime | None = None


class World:
    def __init__(self):
        self.teams: list[TeamInfo] = []
        self.names: dict[str, int] = {}
        self.holidays: set[date] = set()
        self.workdays: set[date] = set()
        self.overrides: dict = {}
        self.workers: dict[str, list[Entry]] = {}
        self.attendance: dict = {}

    def team_id(self, name):
        assert name in self.names, f"没有班组「{name}」"
        return self.names[name]

    def add_team(self, name, info):
        self.names[name] = info.id
        self.teams.append(info)

    def entry(self, worker, d) -> Entry:
        rows = self.workers[worker]
        i = bisect_right([e.effective_from for e in rows], d) - 1
        return rows[max(i, 0)]

    def schedule(self) -> Schedule:
        own = Schedule(tuple(self.teams), holidays=frozenset(self.holidays),
                       extra_workdays=frozenset(self.workdays), overrides=dict(self.overrides))
        nonmain = {t.id for t in self.teams if not t.is_main}
        if not nonmain or not self.workers:
            return own

        def member_fn(d):  # 和 schedule_service.member_days 一样：用不带这一条的排班算成员出勤
            days = [d - timedelta(days=3) + timedelta(days=i) for i in range(35)]
            rows = [{x: att.resolve(own, self.entry(w, x), self.attendance.get((w, x)), x) for x in days}
                    for w in self.workers]
            out = {x: {} for x in days}
            for x, shifts in vote_member_shifts(rows, nonmain).items():
                out[x].update(shifts)
            return out

        return replace(own, member_fn=member_fn, _member_cache={})


def D(s):
    return date.fromisoformat(s)


def cycle_tokens(text):
    return tuple(KIND.get(x, x) for x in text.split())


def parse_setup(lines) -> World:
    w = World()
    for line in lines:
        if line == "标准排班":
            for name, info in (("1班", rotating(1, 4)), ("2班", rotating(2, 6)), ("3班", rotating(3, 0)),
                               ("4班", rotating(4, 2)), ("常白班", day_team(5))):
                w.add_team(name, info)
        elif m := re.fullmatch(r"(不固定)?班组「(.+?)」(?:：循环 (.+?)，第 1 天 (\S+?))?((?:，.+)?)", line):
            manual, name, pat, start, opts = m.groups()
            assert bool(manual) != bool(pat), line
            af = at = None
            if mm := re.search(r"有效期 (\S+?) 至 ?(\S*)", opts):
                af, at = D(mm[1]), D(mm[2]) if mm[2] else None
            cyc = None if manual else Cycle(cycle_tokens(pat), D(start), "节假日休息" in opts)
            w.add_team(name, TeamInfo(len(w.teams) + 1, cyc, "主班组" in opts, af, at))
        elif m := re.fullmatch(r"(节假日|调休上班) (.+)", line):
            (w.holidays if m[1] == "节假日" else w.workdays).update(D(x) for x in m[2].split("、"))
        elif m := re.fullmatch(r"班组调班：「(.+?)」(\S+) 改为 (\S+)", line):
            w.overrides[(w.team_id(m[1]), D(m[2]))] = KIND.get(m[3], m[3])
        elif m := re.fullmatch(r"员工「(.+?)」(?:从 (\S+) 起)?属于「(.+?)」(?:，个人循环 (.+?)，第 1 天 (\S+))?", line):
            name, since, team, pat, start = m.groups()
            cyc = Cycle(cycle_tokens(pat), D(start)) if pat else None
            rows = w.workers.setdefault(name, [])
            rows.append(Entry(D(since) if since else EPOCH, w.team_id(team), cyc))
            rows.sort(key=lambda e: e.effective_from)
        elif m := re.fullmatch(r"出勤：「(.+?)」(\S+) (出勤|请假|病假|缺勤|休息)(?: 顶「(.+?)」)?(?: (白|中|夜)班)?", line):
            name, day, st, cover, kind = m.groups()
            assert name in w.workers, f"没有员工「{name}」"
            w.attendance[(name, D(day))] = Rec(STATUS[st], KIND[kind] if kind else None,
                                               w.team_id(cover) if cover else None)
        else:
            raise AssertionError(f"看不懂的设置：{line}")
    return w


def parse_doc():
    out = []
    for block in re.split(r"^## ", DOC.read_text(encoding="utf-8"), flags=re.M):
        if not block.startswith("场景"):
            continue
        title = block.splitlines()[0]
        setup, table = [], []
        in_setup = False
        for line in block.splitlines()[1:]:
            if line.startswith("设置："):
                in_setup = True
            elif in_setup and line.startswith("- "):
                setup.append(line[2:].strip())
            elif line.startswith("|"):
                in_setup = False
                table.append([c.strip() for c in line.strip().strip("|").split("|")])
        assert setup and len(table) > 2, title
        head, rows = table[0], [r for r in table[2:]]
        out.append((title, setup, [dict(zip(head, r)) for r in rows]))
    return out


SCENARIOS = parse_doc()


def reasons(trace):
    return "、".join(dict.fromkeys(REASON[s["code"]] for s in trace if s["code"] in REASON)) or NONE


def group_main(w, sched, team_id, d, kind):
    team = sched.team(team_id)
    if team is None or kind in (None, OFF):
        return NONE
    main = sched.group_of(team, d, kind)[0] if sched.is_on(team, d, kind) else sched.main_team_on(d, kind)
    return next((n for n, i in w.names.items() if main and i == main.id), NONE)


def check_row(w, sched, row):
    d, who = D(row["日期"]), row["谁"]
    trace: list = []
    if m := re.fullmatch(r"时刻 (\d\d):(\d\d)", who):
        sd, kind = sched.shift_at(datetime.combine(d, datetime.min.time()) + timedelta(hours=int(m[1]), minutes=int(m[2])))
        got = {"结果": f"{sd:%m-%d} {KIND_NAME[kind]}", "原因": NONE,
               "显示在": next((n for n, i in w.names.items() if (t := sched.main_team_on(sd, kind)) and t.id == i), NONE)}
    elif m := re.fullmatch(r"班组「(.+?)」", who):
        tid = w.team_id(m[1])
        kind = sched.shift_of(sched.team(tid), d, trace)
        entry = sched.team_entry(sched.team(tid), d)
        res = KIND_NAME[kind] + (f" {entry}" if entry not in KIND_NAME else "")
        got = {"结果": res, "原因": reasons(trace), "显示在": group_main(w, sched, tid, d, kind)}
    elif m := re.fullmatch(r"「(.+?)」", who):
        name = m[1]
        assert name in w.workers, f"没有员工「{name}」"
        e = w.entry(name, d)
        r = att.resolve(sched, e, w.attendance.get((name, d)), d, trace)
        if r.status == "present":
            res = KIND_NAME[r.shift_kind] if r.shift_kind else "出勤"
            if r.hours:
                res += f" {r.hours}"
            if r.team_id != e.team_id:
                res += f"（顶 {next(n for n, i in w.names.items() if i == r.team_id)}）"
        else:
            res = STATUS_NAME[r.status]
        got = {"结果": res, "原因": reasons(trace),
               "显示在": group_main(w, sched, r.team_id, d, r.shift_kind) if r.status == "present" else NONE}
    else:
        raise AssertionError(f"看不懂的「谁」：{who}")
    for col in ("结果", "原因", "显示在"):
        want = row.get(col, "")
        if want:
            assert got[col] == want, f"{row['日期']} {who} 的「{col}」：表里写 {want}，系统算出 {got[col]}\n依据：{trace}"


@pytest.mark.parametrize("title,setup,rows", SCENARIOS, ids=[s[0].split("：")[0] for s in SCENARIOS])
def test_scenario(title, setup, rows):
    w = parse_setup(setup)
    sched = w.schedule()
    for row in rows:
        check_row(w, sched, row)


def test_doc_has_scenarios():
    assert len(SCENARIOS) >= 10
