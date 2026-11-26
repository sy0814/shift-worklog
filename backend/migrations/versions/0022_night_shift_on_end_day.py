"""夜班改为归属结束（下班）的那一天（和工厂出勤表一致：3 = 前一天 23:00 到当天 07:00）

以前：11-21 23:00 ~ 11-22 07:00 记为 11-21 的夜班；现在记为 11-22 的夜班。实际上班的时间一点都不变，
只是「记在哪一天」变了，所以已有数据要跟着挪：
  - 任务、班次日志、加班：夜班的日期 +1 天
  - 班组循环、个人循环：每天的安排重新表达，例如「白 白 中 中 夜 夜 休 休」→「白 白 中 中 休 夜 夜 休」
    （第 i 天的夜班挪到第 i+1 天；同一天既有挪过来的夜班又有白班 / 中班时，写成自定义时间段）
  - 班组调班：按旧规则算出每天实际上的班，换成新规则后和新循环不一样的日子写成调班
  - 出勤例外：那天实际上的是夜班（写明夜班，或没写班次、按排班是夜班）的记录日期 +1 天
自定义时间段：跨午夜的段、夜班开始（23:00）以后开始的段、凌晨（白班开始以前）开始的段属于夜班部分，挪到第二天。
这里的推算按旧规则单独写一份（不用 app.shifts，它已经是新规则了）。

Revision ID: 0022
Revises: 0021
"""

import re
from collections import Counter
from datetime import date, time, timedelta

import sqlalchemy as sa
from alembic import op

revision = "0022"
down_revision = "0021"
branch_labels = None
depends_on = None

DAY, MIDDLE, NIGHT, OFF = "day", "middle", "night", "off"
KINDS = (DAY, MIDDLE, NIGHT, OFF)
OLD_ORDER = (DAY, MIDDLE, NIGHT)
_HOURS = re.compile(r"^(\d{2}):(\d{2})-(\d{2}):(\d{2})$")
ONE = timedelta(days=1)


def _mins(t: time) -> int:
    return t.hour * 60 + t.minute


def _segs(entry: str) -> list[tuple[str, int, int]] | None:
    """"07:00-12:00,23:00-03:00" → [("07:00-12:00", 420, 720), ...]（分钟按钟面）；不是时间段返回 None。"""
    if entry in KINDS:
        return None
    out = []
    for part in entry.split(","):
        m = _HOURS.match(part.strip())
        if not m:
            return None
        h1, m1, h2, m2 = map(int, m.groups())
        out.append((part.strip(), h1 * 60 + m1, h2 * 60 + m2))
    return out


class Cfg:
    def __init__(self, day_start: time, middle_start: time, night_start: time):
        self.d, self.m, self.n = _mins(day_start), _mins(middle_start), _mins(night_start)
        self.t = {DAY: f"{day_start:%H:%M}-{middle_start:%H:%M}", MIDDLE: f"{middle_start:%H:%M}-{night_start:%H:%M}",
                  NIGHT: f"{night_start:%H:%M}-{day_start:%H:%M}"}

    def is_night_seg(self, a: int, b: int) -> bool:
        """旧规则下这一段属于夜班部分（新规则记到第二天）：跨午夜、夜班开始以后开始、或凌晨开始。"""
        return b <= a or a >= self.n or a < self.d

    def _evening(self, t: str) -> bool:
        a, b = int(t[:2]) * 60 + int(t[3:5]), int(t[6:8]) * 60 + int(t[9:11])
        return b <= a or a >= self.n

    def old_kind(self, entry: str) -> str:
        """旧规则：时间段算哪个班（重叠最多；凌晨开始的算这天夜班的后半段）。"""
        segs = _segs(entry)
        if segs is None:
            return entry
        mins = []
        for _t, x, y in segs:
            if y <= x:
                y += 1440
            if x < self.d:
                x, y = x + 1440, y + 1440
            mins.append((x, y))
        best, best_ov = DAY, -1
        for kind, s0, e0 in ((DAY, self.d, self.m), (MIDDLE, self.m, self.n), (NIGHT, self.n, self.d + 1440)):
            ov = sum(max(0, min(y, e0) - max(x, s0)) for x, y in mins)
            if ov > best_ov:
                best, best_ov = kind, ov
        return best

    def split(self, entry: str) -> tuple[list[str], list[str]]:
        """旧规则的一天 → (夜班部分, 其余部分)，都是时间段文字列表；整班写法也换成时间段。"""
        segs = _segs(entry)
        if segs is None:
            if entry == NIGHT:
                return [self.t[NIGHT]], []
            if entry in (DAY, MIDDLE):
                return [], [self.t[entry]]
            return [], []
        night = [t for t, a, b in segs if self.is_night_seg(a, b)]
        rest = [t for t, a, b in segs if not self.is_night_seg(a, b)]
        return night, rest

    def combine(self, prev_entry: str, entry: str) -> str:
        """新规则下这一天 = 前一天（旧）的夜班部分 + 这一天（旧）除夜班以外的部分。能写成整班的写成整班。"""
        pn, _ = self.split(prev_entry)
        _, rest = self.split(entry)
        if not pn and not rest:
            return OFF
        # 夜班部分：前一天晚上开始的（跨午夜或 23:00 以后）在前，凌晨开始的在后；其余部分按开始时间
        pn.sort(key=lambda t: (0 if self._evening(t) else 1, t))
        rest.sort()
        parts = pn + rest
        if len(parts) == 1:
            for k, txt in self.t.items():
                if parts[0] == txt:
                    return k
        return ",".join(parts[:4])


def _planned(pattern, start, holiday_off, d, holidays, workdays) -> str:
    """旧的 Cycle.planned（节假日休息、调休上班按主要班次）。"""
    k = pattern[(d - start).days % len(pattern)]
    if holiday_off:
        if d in holidays:
            return OFF
        if d in workdays and k == OFF:
            c = Counter(x for x in pattern if x != OFF)
            if not c:
                return DAY
            rank = {x: i for i, x in enumerate(OLD_ORDER)}
            return max(c, key=lambda x: (c[x], -rank.get(x, 9)))
    return k


def _new_pattern(cfg: Cfg, pattern: list) -> list:
    n = len(pattern)
    return [cfg.combine(pattern[(i - 1) % n], pattern[i]) for i in range(n)]


def upgrade() -> None:
    conn = op.get_bind()
    c = sa.column
    T = lambda name, *cols: sa.table(name, c("id", sa.Integer), *cols)
    shift_config = T("shift_config", c("day_start", sa.Time), c("middle_start", sa.Time), c("night_start", sa.Time))
    holidays_t = sa.table("holidays", c("day", sa.Date), c("kind", sa.String))
    teams = T("teams", c("kind", sa.String), c("pattern", sa.JSON), c("cycle_start", sa.Date), c("holiday_off", sa.Boolean))
    ws = T("worker_schedules", c("worker_id", sa.Integer), c("effective_from", sa.Date), c("team_id", sa.Integer),
           c("pattern", sa.JSON), c("cycle_start", sa.Date), c("holiday_off", sa.Boolean))
    ovr = T("team_shift_overrides", c("team_id", sa.Integer), c("day", sa.Date), c("shift_kind", sa.String),
            c("hours", sa.String), c("note", sa.String), c("created_by", sa.Integer),
            c("created_at", sa.DateTime(timezone=True)))
    att = T("attendance", c("worker_id", sa.Integer), c("day", sa.Date), c("status", sa.String),
            c("shift_kind", sa.String), c("team_id", sa.Integer), c("note", sa.String))
    workers = T("workers", c("team_id", sa.Integer))

    row = conn.execute(sa.select(shift_config.c.day_start, shift_config.c.middle_start, shift_config.c.night_start)
                       .where(shift_config.c.id == 1)).first()
    cfg = Cfg(*(row if row else (time(7), time(15), time(23))))

    # 1. 任务、班次日志、加班：夜班日期 +1
    for name, dcol in (("tasks", "shift_date"), ("task_logs", "shift_date"), ("overtime", "day")):
        t = T(name, c(dcol, sa.Date), c("shift_kind", sa.String))
        for rid, d in conn.execute(sa.select(t.c.id, t.c[dcol]).where(t.c.shift_kind == NIGHT)).all():
            conn.execute(sa.update(t).where(t.c.id == rid).values({dcol: d + ONE}))

    hol_rows = conn.execute(sa.select(holidays_t.c.day, holidays_t.c.kind)).all()
    holidays = frozenset(d for d, k in hol_rows if k != "workday")
    workdays = frozenset(d for d, k in hol_rows if k == "workday")

    # 旧规则下：班组某天的安排（调班优先，否则循环）
    team_rows = {r.id: r for r in conn.execute(sa.select(teams)).all()}
    old_ovr: dict[tuple[int, date], str] = {}
    ovr_rows = conn.execute(sa.select(ovr)).all()
    for o in ovr_rows:
        old_ovr[(o.team_id, o.day)] = o.hours or o.shift_kind

    def old_team_entry(tid: int, d: date) -> str:
        if (tid, d) in old_ovr:
            return old_ovr[(tid, d)]
        t = team_rows.get(tid)
        if t is None or t.kind != "cycle" or not t.pattern or not t.cycle_start:
            return OFF
        return _planned(list(t.pattern), t.cycle_start, bool(t.holiday_off), d, holidays, workdays)

    ws_rows = conn.execute(sa.select(ws).order_by(ws.c.worker_id, ws.c.effective_from)).all()
    worker_team = {r.id: r.team_id for r in conn.execute(sa.select(workers.c.id, workers.c.team_id)).all()}

    def old_worker_kind(wid: int, d: date, cover_team: int | None) -> str:
        """旧规则：这个人这天默认上的班（顶别的班组 → 被顶班组的班）。"""
        if cover_team:
            return cfg.old_kind(old_team_entry(cover_team, d))
        cur = None
        for r in ws_rows:
            if r.worker_id == wid and r.effective_from <= d:
                cur = r
        if cur is not None and cur.pattern and cur.cycle_start:
            return cfg.old_kind(_planned(list(cur.pattern), cur.cycle_start, bool(cur.holiday_off), d, holidays, workdays))
        tid = cur.team_id if cur is not None else worker_team.get(wid)
        return cfg.old_kind(old_team_entry(tid, d)) if tid else OFF

    # 2. 出勤例外（先用旧规则判断，再改排班）
    moves, absent_after_night = [], []
    for a in conn.execute(sa.select(att)).all():
        kind = a.shift_kind or (old_worker_kind(a.worker_id, a.day, a.team_id) if a.status != OFF else None)
        if kind == NIGHT:
            moves.append(a)
        elif not a.shift_kind and a.status in ("leave", "sick", "absent") and kind == OFF \
                and old_worker_kind(a.worker_id, a.day - ONE, a.team_id) == NIGHT:
            # 旧规则下：前一晚上了夜班、这天（休息日）记了请假。新规则下这天的班就是那个夜班，
            # 留着会把上过的夜班变成请假。前一晚也请假的话，下面挪过来的那条会顶替它
            absent_after_night.append(a.id)
    moving = {a.id for a in moves}
    for a in sorted(moves, key=lambda a: a.day, reverse=True):  # 从后往前挪，连续几天的不会互相挡住
        target = a.day + ONE
        other = conn.execute(sa.select(att.c.id, att.c.status).where(att.c.worker_id == a.worker_id,
                                                                     att.c.day == target)).first()
        if other is not None and other.id not in moving:
            # 那天已经有一条（旧规则下第二天白班 / 中班 / 休息的记录）：状态一样就只留一条，不一样留夜班这条
            conn.execute(sa.delete(att).where(att.c.id == other.id))
            if other.status != a.status:
                note = ((a.note or "") + f" [0022: {target} {other.status}]").strip()[:200]
                conn.execute(sa.update(att).where(att.c.id == a.id).values(note=note))
        conn.execute(sa.update(att).where(att.c.id == a.id).values(day=target))
        moving.discard(a.id)
    moved_ids = {a.id for a in moves}
    for aid in absent_after_night:
        if aid not in moved_ids:
            conn.execute(sa.delete(att).where(att.c.id == aid))

    # 3. 班组调班：按旧规则算出受影响的日子实际上的班，换成新规则；和新循环一样的不存
    new_pattern = {tid: _new_pattern(cfg, list(t.pattern)) for tid, t in team_rows.items()
                   if t.kind == "cycle" and t.pattern and t.cycle_start}
    touched: dict[int, set] = {}
    for o in ovr_rows:
        touched.setdefault(o.team_id, set()).update({o.day, o.day + ONE})
    keep = {o.team_id: o for o in ovr_rows}  # 新建的调班沿用这个班组某条旧调班的创建人
    by_key = {(o.team_id, o.day): o for o in ovr_rows}
    conn.execute(sa.delete(ovr))
    for tid, days in touched.items():
        t = team_rows.get(tid)
        for d in sorted(days):
            entry = cfg.combine(old_team_entry(tid, d - ONE), old_team_entry(tid, d))
            if tid in new_pattern:
                planned = _planned(new_pattern[tid], t.cycle_start, bool(t.holiday_off), d, holidays, workdays)
            else:
                planned = OFF
            if entry == planned:
                continue
            src = by_key.get((tid, d)) or by_key.get((tid, d - ONE)) or keep[tid]
            segs = _segs(entry)
            kind = entry if segs is None else _new_kind(cfg, entry)
            conn.execute(sa.insert(ovr).values(team_id=tid, day=d, shift_kind=kind, hours=entry if segs else None,
                                               note=src.note or "", created_by=src.created_by,
                                               created_at=src.created_at))

    # 4. 循环：班组、个人
    for tid, pat in new_pattern.items():
        conn.execute(sa.update(teams).where(teams.c.id == tid).values(pattern=pat))
    for r in ws_rows:
        if r.pattern:
            conn.execute(sa.update(ws).where(ws.c.id == r.id).values(pattern=_new_pattern(cfg, list(r.pattern))))


def _new_kind(cfg: Cfg, entry: str) -> str:
    """新规则：时间段算哪个班（夜班开始以后开始的段在前一天晚上）。"""
    mins = []
    for _t, x, y in _segs(entry):
        if y <= x:  # 跨午夜：前一天晚上开始
            x -= 1440
        elif x >= cfg.n:
            x, y = x - 1440, y - 1440
        mins.append((x, y))
    best, best_ov = NIGHT, -1
    for kind, s0, e0 in ((NIGHT, cfg.n - 1440, cfg.d), (DAY, cfg.d, cfg.m), (MIDDLE, cfg.m, cfg.n)):
        ov = sum(max(0, min(y, e0) - max(x, s0)) for x, y in mins)
        if ov > best_ov:
            best, best_ov = kind, ov
    return best


def downgrade() -> None:
    """反过来挪（只为开发时能退回去；出勤里没写班次的记录、调班不反推）：夜班日期 -1，循环按相反方向重新表达。"""
    conn = op.get_bind()
    c = sa.column
    T = lambda name, *cols: sa.table(name, c("id", sa.Integer), *cols)
    shift_config = T("shift_config", c("day_start", sa.Time), c("middle_start", sa.Time), c("night_start", sa.Time))
    row = conn.execute(sa.select(shift_config.c.day_start, shift_config.c.middle_start, shift_config.c.night_start)
                       .where(shift_config.c.id == 1)).first()
    cfg = Cfg(*(row if row else (time(7), time(15), time(23))))
    for name, dcol in (("tasks", "shift_date"), ("task_logs", "shift_date"), ("overtime", "day"),
                       ("attendance", "day"), ("team_shift_overrides", "day")):
        t = T(name, c(dcol, sa.Date), c("shift_kind", sa.String))
        for rid, d in conn.execute(sa.select(t.c.id, t.c[dcol]).where(t.c.shift_kind == NIGHT)).all():
            conn.execute(sa.update(t).where(t.c.id == rid).values({dcol: d - ONE}))

    def old_pattern(pat: list) -> list:
        n = len(pat)
        out = []
        for i in range(n):
            _, rest = cfg.split(pat[i])
            night, _ = cfg.split(pat[(i + 1) % n])
            parts = sorted(rest) + sorted(night, key=lambda t: (0 if cfg._evening(t) else 1, t))
            if not parts:
                out.append(OFF)
            elif len(parts) == 1 and parts[0] in cfg.t.values():
                out.append(next(k for k, v in cfg.t.items() if v == parts[0]))
            else:
                out.append(",".join(parts[:4]))
        return out

    for name in ("teams", "worker_schedules"):
        t = T(name, c("pattern", sa.JSON))
        for rid, pat in conn.execute(sa.select(t.c.id, t.c.pattern)).all():
            if pat:
                conn.execute(sa.update(t).where(t.c.id == rid).values(pattern=old_pattern(list(pat))))
