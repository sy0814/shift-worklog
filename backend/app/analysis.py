"""AI 工作量分析。

数字全部由程序算好（build_stats），模型只拿到统计结果和少量任务摘要，负责写分析报告。
这样报告里的每个数字都能在页面上的统计表里核对。
"""

import json
import logging
import statistics
import threading
import time
from datetime import date, datetime, timedelta, timezone

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from . import attendance_service as att
from . import app_settings, llm_config, translation_service
from .config import get_settings
from .db import SessionLocal
from .models import AiReport, Task, TaskHandover, Team, Worker, utcnow
from .schedule_service import load_schedule

log = logging.getLogger("analysis")
OPEN = ("not_started", "in_progress")
SAMPLES_PER_PERSON = 6
ANALYSIS_TIMEOUT = 240.0


def _aware(d: datetime | None) -> datetime | None:
    if d is not None and d.tzinfo is None:
        return d.replace(tzinfo=timezone.utc)
    return d


def _hours(t: Task) -> float | None:
    if t.start_at and t.end_at:
        return round((_aware(t.end_at) - _aware(t.start_at)).total_seconds() / 3600, 2)
    return None


def _text(t: Task, lang: str) -> str:
    src = getattr(t, f"content_{t.source_lang}") or ""
    return (getattr(t, f"content_{lang}") or src).replace("\n", " ")[:80]


def build_stats(db: Session, start: date, end: date, team_id: int | None, lang: str) -> dict:
    """按人、按班组汇总。时间段按班次日期；工时 = 完成 − 开始，多人参与时每人都计全部工时。"""
    teams = {t.id: t for t in db.scalars(select(Team))}
    tname = lambda tid: getattr(teams[tid], f"name_{lang}") if tid in teams else "-"
    now = utcnow()
    cfg_overdue = app_settings.get_all(db)

    q = select(Task).options(selectinload(Task.workers)).where(Task.shift_date >= start, Task.shift_date <= end)
    if team_id:
        q = q.where(Task.team_id == team_id)
    tasks = list(db.scalars(q))

    wq = select(Worker).where(Worker.is_active.is_(True))
    if team_id:
        wq = wq.where(Worker.team_id == team_id)
    workers = {w.id: w for w in db.scalars(wq)}
    for t in tasks:  # 来帮忙的其他班组员工也算
        for w in t.workers:
            workers.setdefault(w.id, w)
    eff = att.effective(db, list(workers.values()), start, end)
    sched = load_schedule(db)
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]

    def overdue(t: Task) -> bool:
        if t.status not in OPEN:
            return False
        age = (now - _aware(t.chain_started_at)).total_seconds() / 3600
        return age >= cfg_overdue["overdue_hours"] or t.handover_count >= cfg_overdue["overdue_handovers"]

    people = []
    for w in sorted(workers.values(), key=lambda x: (x.team_id or 999, x.name)):
        mine = [t for t in tasks if any(x.id == w.id for x in t.workers)]
        row = eff[w.id]
        present = sum(1 for a in row.values() if a.status == "present")
        hours = round(sum(h for t in mine if (h := _hours(t)) is not None), 1)
        people.append({
            "name": w.name,
            "team": tname(w.team_id),
            "scheduled_shifts": sum(1 for d in days if att.default_for(sched, w, d).status == "present"),
            "present_shifts": present,
            "leave": sum(1 for a in row.values() if a.status == "leave"),
            "sick": sum(1 for a in row.values() if a.status == "sick"),
            "absent": sum(1 for a in row.values() if a.status == "absent"),
            "cover_shifts_for_other_teams": sum(1 for a in row.values()
                                                if a.status == "present" and a.team_id and a.team_id != w.team_id),
            "tasks": len(mine),
            "done": sum(1 for t in mine if t.status == "done"),
            "open": sum(1 for t in mine if t.status in OPEN),
            "handed_over": sum(1 for t in mine if t.status == "handed_over"),
            "discarded": sum(1 for t in mine if t.status == "discarded"),
            "task_hours": hours,
            "hours_per_present_shift": round(hours / present, 2) if present else None,
            "open_overdue": sum(1 for t in mine if overdue(t)),
            "sample_tasks": [_text(t, lang) for t in sorted(mine, key=lambda t: t.created_at)[:SAMPLES_PER_PERSON]],
        })

    ids = [t.id for t in tasks]
    hos = list(db.scalars(select(TaskHandover).where(
        TaskHandover.from_task_id.in_(ids) | TaskHandover.to_task_id.in_(ids)))) if ids else []
    team_rows = []
    for tid in sorted({t.team_id for t in tasks} | ({team_id} if team_id else set(teams))):
        tt = [t for t in tasks if t.team_id == tid]
        done_h = [h for t in tt if t.status == "done" and (h := _hours(t)) is not None]
        members = [p for p in people if p["team"] == tname(tid)]
        counts = [p["tasks"] for p in members]
        team_rows.append({
            "team": tname(tid),
            "kind": teams[tid].kind if tid in teams else "",
            "tasks": len(tt),
            "by_status": {s: sum(1 for t in tt if t.status == s) for s in ("not_started", "in_progress", "done", "handed_over", "discarded")},
            "handovers_out": sum(1 for h in hos if h.from_team_id == tid),
            "handovers_in": sum(1 for h in hos if h.to_team_id == tid),
            "open_overdue": sum(1 for t in tt if overdue(t)),
            "max_handover_count": max((t.handover_count for t in tt), default=0),
            "avg_task_hours_done": round(statistics.mean(done_h), 2) if done_h else None,
            "tasks_without_workers": sum(1 for t in tt if not t.workers and t.status != "discarded"),
            "members": len(members),
            "tasks_per_member": {"min": min(counts), "median": statistics.median(counts), "max": max(counts)} if counts else None,
            "members_present_but_no_tasks": [p["name"] for p in members if p["present_shifts"] > 0 and p["tasks"] == 0],
        })

    return {
        "period": {"start": start.isoformat(), "end": end.isoformat(), "days": len(days)},
        "scope_team": tname(team_id) if team_id else None,
        "rules": {
            "shift_hours": 8,
            "task_hours": "end - start; a task with several workers counts its full hours for each worker",
            "attendance": "default from the shift schedule; only leave/sick/absent/swaps are recorded explicitly",
            "overdue": f"open and (older than {cfg_overdue['overdue_hours']} h since first entry or handed over >= {cfg_overdue['overdue_handovers']} times)",
            "tasks_without_times": "tasks without start/end time contribute 0 hours",
        },
        "totals": {
            "tasks": len(tasks),
            "with_hours": sum(1 for t in tasks if _hours(t) is not None),
            "people": len(people),
        },
        "teams": team_rows,
        "people": people,
    }


LANG_NAME = {"zh": "简体中文", "sr": "srpski (latinica)", "en": "English"}

SYSTEM_PROMPT = """You are an experienced maintenance and production manager in a mineral processing plant (crushing, grinding, flotation, dewatering, conveying, power distribution). You review how work was distributed among shift teams and workers and write a clear, fair report for plant management.

Rules:
- Use ONLY the statistics provided. Quote the concrete numbers you rely on. Never invent data, names or events.
- The numbers are already computed; do not recalculate them differently. Respect the counting rules given in "rules".
- Judge the arrangement of work (balance between people and teams, handovers, overdue items, unassigned tasks, attendance), not people's character. Be constructive and specific.
- When the data is too thin to conclude (few tasks, many tasks without times, short period), say so explicitly instead of guessing.
- Task hours are counted in full for every participant, so a high number can mean many joint tasks rather than overload; take that into account.
- Never say a threshold or condition was reached (e.g. the overdue rules) unless the statistics show it; "max_handover_count" gives the highest handover count per team.
- Write the whole report in {lang_name}, including all headings and table headers. Use Markdown with exactly these sections:
  {sections}
  In the people table the columns are: name, team, present shifts, tasks, done, open, task hours, hours per shift, assessment ({assess}); after the table comment only on people who stand out. Each problem must give its evidence numbers; recommendations must be concrete, actionable and prioritized.
- Keep people's names exactly as given; but when writing in Serbian or English, write Chinese names as the characters followed by Hanyu Pinyin in brackets, e.g. 张伟 (Zhang Wei). Keep it under about 900 words, excluding tables."""


SECTIONS = {
    "zh": ["## 1. 总体情况（3~5 条要点）", "## 2. 各班组（表格 + 简短说明）", "## 3. 人员（表格 + 需要关注的人）",
           "## 4. 发现的问题", "## 5. 改进建议（按优先级）", "## 6. 数据局限"],
    "sr": ["## 1. Rezime (3–5 tačaka)", "## 2. Ekipe (tabela + kratak komentar)", "## 3. Radnici (tabela + ko se izdvaja)",
           "## 4. Uočeni problemi", "## 5. Preporuke (po prioritetu)", "## 6. Ograničenja podataka"],
    "en": ["## 1. Summary (3-5 bullet points)", "## 2. Teams (table + short comments)", "## 3. People (table + who stands out)",
           "## 4. Problems found", "## 5. Recommendations (prioritized)", "## 6. Data limitations"],
}
ASSESS = {"zh": "均衡 / 偏高 / 偏低 / 数据不足", "sr": "ujednačeno / visoko / nisko / nedovoljno podataka",
          "en": "balanced / high / low / insufficient data"}


def build_messages(stats: dict, lang: str) -> list[dict]:
    system = (SYSTEM_PROMPT.replace("{lang_name}", LANG_NAME[lang])
              .replace("{sections}", "\n  ".join(SECTIONS[lang])).replace("{assess}", ASSESS[lang]))
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": "Statistics (JSON):\n" + json.dumps(stats, ensure_ascii=False)},
    ]


class AnalysisError(Exception):
    pass


def call_model(messages: list[dict]) -> tuple[str, dict, str]:
    """调用分析模型，返回 (报告文本, token 用量, 模型名)。超时 / 5xx / 429 重试 1 次。"""
    cfg = llm_config.current()
    if not cfg.configured:
        raise AnalysisError("AI API not configured")
    model = cfg.analysis_model or cfg.translate_model
    # 分析允许模型思考（质量更好），所以不带翻译用的「关闭思考」参数
    body = {"model": model, "messages": messages, "stream": False}
    headers = {"Authorization": f"Bearer {cfg.api_key}"}
    url = cfg.base_url.rstrip("/") + "/chat/completions"
    last = None
    with translation_service.client_factory() as client:
        for attempt in range(2):
            if attempt:
                time.sleep(3)
            try:
                r = client.post(url, json=body, headers=headers, timeout=ANALYSIS_TIMEOUT)
            except httpx.HTTPError as e:
                last = f"network: {e}"
                continue
            if r.status_code == 429 or r.status_code >= 500:
                last = f"HTTP {r.status_code}: {r.text[:200]}"
                continue
            if r.status_code != 200:
                raise AnalysisError(f"HTTP {r.status_code}: {r.text[:300]}")
            try:
                j = r.json()
                text = (j["choices"][0]["message"]["content"] or "").strip()
            except (ValueError, KeyError, IndexError, TypeError):
                raise AnalysisError(f"unexpected response: {r.text[:300]}")
            if not text:
                last = "empty report"
                continue
            usage = {k: v for k, v in (j.get("usage") or {}).items() if isinstance(v, (int, float))}
            return text, usage, model
    raise AnalysisError(f"failed after 2 tries: {last}")


def run_report(report_id: int) -> None:
    """后台执行：算统计 → 调模型 → 存报告。"""
    with SessionLocal() as db:
        rep = db.get(AiReport, report_id)
        if rep is None or rep.status not in ("pending", "failed"):
            return
        rep.status = "running"
        db.commit()
        try:
            stats = build_stats(db, rep.start, rep.end, rep.team_id, rep.lang)
            rep.stats = stats
            db.commit()
            if stats["totals"]["tasks"] == 0:
                raise AnalysisError("no tasks in the selected period")
            text, usage, model = call_model(build_messages(stats, rep.lang))
            rep.report_md, rep.usage, rep.model = text, usage, model
            rep.status = "done"
        except Exception as e:  # noqa: BLE001  记录任何失败原因，页面上显示
            log.warning("analysis %s failed: %s", report_id, e)
            rep.status = "failed"
            rep.error = str(e)[:1000]
        rep.finished_at = utcnow()
        db.commit()


def start_in_background(report_id: int) -> None:
    threading.Thread(target=run_report, args=(report_id,), daemon=True, name=f"analysis-{report_id}").start()
