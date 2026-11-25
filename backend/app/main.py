from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import audit  # noqa: F401  注册 audit_log 的 after_create 触发器
from . import departments as _departments  # noqa: F401  注册员工车间跟班组同步（before_flush）
from .db import SessionLocal, engine
from . import migrate, translation_service
from .config import get_settings
from .routers import analysis as analysis_router, attendance, departments as departments_router, branding, duty, equipment, explain as explain_router, task_logs, overtime, inspections, audit_log, auth, export, handover, llm_settings, projects, roles, schedule, storage, tasks, translation, users, workers
from .seed import seed, seed_glossary
from .security import require_admin

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"  # 前端构建产物


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 数据库结构升级到最新版本（Alembic 迁移，数据保留）
    migrate.upgrade(engine)
    with SessionLocal() as db:
        seed(db)
        seed_glossary(db)
        from .permissions import ensure_builtin_roles

        ensure_builtin_roles(db)  # 新版本加的内置角色（例如车间管理员）
        db.commit()
    if get_settings().run_scheduler:
        translation_service.start_workers()  # 翻译队列的后台线程
        translation_service.start_scheduler()  # 定时把待翻译的任务放进队列
    yield
    translation_service.stop_scheduler()
    translation_service.stop_workers()


app = FastAPI(title="工作记录系统", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(departments_router.router)
app.include_router(branding.router)
app.include_router(overtime.router)
app.include_router(users.router)
app.include_router(roles.router)
app.include_router(projects.router)
app.include_router(equipment.router)
app.include_router(storage.router)
app.include_router(schedule.router)
app.include_router(audit_log.router)
app.include_router(workers.router)
app.include_router(tasks.router)
app.include_router(task_logs.router)
app.include_router(handover.router)
app.include_router(translation.router)
app.include_router(attendance.router)
app.include_router(explain_router.router)
app.include_router(export.router)
app.include_router(llm_settings.router)
app.include_router(analysis_router.router)
app.include_router(inspections.router)
app.include_router(duty.router)


@app.get("/api/health")
def health():
    return {"ok": True}


@app.get("/api/alerts")
def get_alerts(_=Depends(require_admin)):
    """管理员首页的红色提醒：备份失败 / 太久没备份、磁盘快满（见 app/alerts.py）。"""
    from . import alerts
    from .schedule_service import local_now

    return alerts.current(local_now())


# 缓存策略：带哈希的静态文件永久缓存；index.html / sw.js / manifest 每次都要检查更新（否则新版本推不下去）
NO_CACHE_FILES = {"index.html", "sw.js", "manifest.webmanifest", "registerSW.js"}


class ImmutableStatic(StaticFiles):
    async def get_response(self, path, scope):
        resp = await super().get_response(path, scope)
        if resp.status_code == 200:
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        return resp


if STATIC_DIR.exists():
    app.mount("/assets", ImmutableStatic(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            raise HTTPException(404)  # 不存在的接口不要返回页面
        f = STATIC_DIR / path
        if not (path and f.is_file() and STATIC_DIR in f.resolve().parents):
            f = STATIC_DIR / "index.html"
        headers = {"Cache-Control": "no-cache"} if f.name in NO_CACHE_FILES or f.name.startswith("workbox-") \
            else {"Cache-Control": "public, max-age=86400"}
        media = "application/manifest+json" if f.suffix == ".webmanifest" else None
        return FileResponse(f, headers=headers, media_type=media)
