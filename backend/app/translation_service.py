"""把翻译结果写回任务：录入后在后台翻译，不阻塞录入；失败的由定时任务重试。

每条任务有三段需要翻译的文字：content（内容）、leftover（遗留问题）、discard_reason（废弃原因）。
各自记录原文语言；人工校对过的译文（manual_fields）不会被机器翻译覆盖。
"""

import logging
import queue
import threading
from collections.abc import Callable

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import audit, translator
from .config import get_settings
from .db import SessionLocal
from .models import GlossaryTerm, Task, utcnow

log = logging.getLogger("translation")

LANGS = translator.LANGS
# 字段 → 记录原文语言的列
FIELDS = {"content": "source_lang", "leftover": "leftover_source_lang", "discard_reason": "discard_reason_lang"}

# 测试时替换成 MockTransport 的 client
client_factory: Callable[[], httpx.Client] = lambda: httpx.Client(timeout=get_settings().translate_timeout)

_running: set[int] = set()
_lock = threading.Lock()


def load_glossary(db: Session) -> list[translator.GlossaryEntry]:
    rows = db.scalars(select(GlossaryTerm).order_by(GlossaryTerm.id)).all()
    return [translator.GlossaryEntry(r.zh, r.sr, r.en) for r in rows]


def source_text(task: Task, field: str) -> tuple[str | None, str | None]:
    lang = getattr(task, FIELDS[field])
    if not lang:
        return None, None
    return lang, getattr(task, f"{field}_{lang}")


def needs_translation(task: Task, field: str) -> bool:
    lang, text = source_text(task, field)
    if not text:
        return False
    manual = set(task.manual_fields or [])
    return any(not getattr(task, f"{field}_{l}") and f"{field}_{l}" not in manual
               for l in LANGS if l != lang)


def pending_fields(task: Task) -> list[str]:
    return [f for f in FIELDS if needs_translation(task, f)]


def refresh_status(task: Task) -> None:
    """根据各字段是否还缺译文，更新任务的翻译状态。"""
    if not pending_fields(task):
        task.translation_status = "done"
        task.translation_error = None
        task.translation_attempts = 0
    elif task.translation_status == "done":
        task.translation_status = "pending"


def mark_text_changed(task: Task, field: str, retranslate: bool = True) -> None:
    """原文改动后调用。retranslate=True：清掉旧译文（含人工校对的）等待重新翻译。"""
    if retranslate:
        lang = getattr(task, FIELDS[field])
        task.manual_fields = [m for m in (task.manual_fields or []) if not m.startswith(field + "_")]
        for l in LANGS:
            if l != lang:
                setattr(task, f"{field}_{l}", None)
    task.translation_attempts = 0
    task.translation_error = None
    refresh_status(task)


def _apply(db: Session, task: Task, field: str, src_text: str, result: translator.Translation) -> None:
    manual = set(task.manual_fields or [])
    old_lang = getattr(task, FIELDS[field])
    new = {FIELDS[field]: result.source_lang}
    for l in LANGS:
        col = f"{field}_{l}"
        if l == result.source_lang:
            new[col] = src_text  # 原文原样保留（模型判断的语言可能和录入时界面语言不同）
        elif col in manual and l != old_lang:
            continue  # 人工校对过的不覆盖
        else:
            new[col] = result.get(l)
    for k, v in new.items():
        setattr(task, k, v)
    audit.log(db, user_id=None, action="translate", entity="task", entity_id=task.id, field=field,
              new={k: v for k, v in new.items()}, extra={"detected": result.source_lang, "recorded": old_lang})


def translate_task(task_id: int) -> str:
    """翻译一条任务缺的译文。返回最终状态。可在后台线程里调用。"""
    with _lock:
        if task_id in _running:
            return "running"
        _running.add(task_id)
    try:
        return _translate_task(task_id)
    finally:
        with _lock:
            _running.discard(task_id)


def _translate_task(task_id: int) -> str:
    s = get_settings()
    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if task is None:
            return "missing"
        fields = pending_fields(task)
        if not fields:
            refresh_status(task)
            db.commit()
            return task.translation_status
        if not translator.is_configured():
            return task.translation_status  # 没配 Key：保持「待翻译」
        glossary = load_glossary(db)
        jobs = [(f, *source_text(task, f)) for f in fields]
        db.rollback()  # 调接口期间不占着数据库事务

    results, error = {}, None
    with client_factory() as client:
        for field, lang, text in jobs:
            try:
                results[field] = (text, translator.translate(text, glossary, client=client))
            except translator.TranslationError as e:
                error = str(e)
                log.warning("translate task %s %s failed: %s", task_id, field, e)

    with SessionLocal() as db:
        task = db.get(Task, task_id)
        if task is None:
            return "missing"
        for field, (text, result) in results.items():
            # 翻译期间原文被改过 → 这次结果作废，等下一轮
            if source_text(task, field)[1] != text:
                continue
            _apply(db, task, field, text, result)
        if error:
            task.translation_attempts = (task.translation_attempts or 0) + 1
            task.translation_error = error[:1000]
            task.translation_status = "failed" if task.translation_attempts >= s.translate_max_attempts else "pending"
        refresh_status(task)
        db.commit()
        return task.translation_status


# ---------------- 翻译队列 ----------------
# 录入 / 修改后把任务放进队列，由后台线程翻译：请求立即返回、不占数据库连接，
# 同时调用翻译接口的数量也有上限（WORKERS 个）。没有启动后台线程时（如测试）直接当场翻译。
WORKERS = 2
_queue: "queue.Queue[int | None]" = queue.Queue()
_queued: set[int] = set()
_threads: list[threading.Thread] = []


def enqueue(task_id: int) -> None:
    if not _threads:
        translate_task(task_id)
        return
    with _lock:
        if task_id in _queued:
            return
        _queued.add(task_id)
    _queue.put(task_id)


def _work() -> None:
    while True:
        tid = _queue.get()
        if tid is None:
            return
        with _lock:
            _queued.discard(tid)
        try:
            translate_task(tid)
        except Exception:  # noqa: BLE001  一条出错不能让线程退出
            log.exception("translate task %s crashed", tid)


def start_workers() -> None:
    if _threads:
        return
    for i in range(WORKERS):
        t = threading.Thread(target=_work, daemon=True, name=f"translate-{i}")
        t.start()
        _threads.append(t)


def stop_workers() -> None:
    for _ in _threads:
        _queue.put(None)
    _threads.clear()


def retry_pending() -> int:
    """定时任务：把所有待翻译的任务放进队列。返回条数。"""
    if not translator.is_configured():
        return 0
    with SessionLocal() as db:
        ids = db.scalars(select(Task.id).where(Task.translation_status == "pending")
                         .order_by(Task.updated_at).limit(200)).all()
    for tid in ids:
        enqueue(tid)
    return len(ids)


def reset_failed(db: Session, task_ids: list[int] | None = None) -> int:
    """管理员手动重试：把 failed 改回 pending。"""
    q = select(Task).where(Task.translation_status == "failed")
    if task_ids:
        q = q.where(Task.id.in_(task_ids))
    n = 0
    for t in db.scalars(q):
        t.translation_status = "pending"
        t.translation_attempts = 0
        n += 1
    return n


# ---------------- 定时任务 ----------------
_scheduler = None


def start_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    from apscheduler.schedulers.background import BackgroundScheduler

    _scheduler = BackgroundScheduler(timezone="UTC")
    _scheduler.add_job(retry_pending, "interval", seconds=get_settings().translate_retry_seconds,
                       id="translate_retry", max_instances=1, coalesce=True, next_run_time=utcnow())
    # 定期巡查：每分钟检查一次有没有到时间的巡查项
    from . import inspection_service

    _scheduler.add_job(inspection_service.run_due, "interval", seconds=60, id="inspections",
                       max_instances=1, coalesce=True, next_run_time=utcnow())
    _scheduler.start()


def stop_scheduler() -> None:
    global _scheduler
    if _scheduler is not None:
        _scheduler.shutdown(wait=False)
        _scheduler = None
