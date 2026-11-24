from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import audit  # noqa: F401  注册 audit_log 的 after_create 触发器
from .db import SessionLocal, engine
from . import migrate, translation_service
from .config import get_settings
from .routers import analysis as analysis_router, attendance, branding, duty, equipment, overtime, inspections, audit_log, auth, export, handover, llm_settings, projects, roles, schedule, tasks, translation, users, workers
from .seed import seed, seed_glossary

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"  # 前端构建产物


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 数据库结构升级到最新版本（Alembic 迁移，数据保留）
    migrate.upgrade(engine)
    with SessionLocal() as db:
        seed(db)
        seed_glossary(db)
    if get_settings().run_scheduler:
        translation_service.start_workers()  # 翻译队列的后台线程
        translation_service.start_scheduler()  # 定时把待翻译的任务放进队列
    yield
    translation_service.stop_scheduler()
    translation_service.stop_workers()


app = FastAPI(title="工作记录系统", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(branding.router)
app.include_router(overtime.router)
app.include_router(users.router)
app.include_router(roles.router)
app.include_router(projects.router)
app.include_router(equipment.router)
app.include_router(schedule.router)
app.include_router(audit_log.router)
app.include_router(workers.router)
app.include_router(tasks.router)
app.include_router(handover.router)
app.include_router(translation.router)
app.include_router(attendance.router)
app.include_router(export.router)
app.include_router(llm_settings.router)
app.include_router(analysis_router.router)
app.include_router(inspections.router)
app.include_router(duty.router)


@app.get("/api/health")
def health():
    return {"ok": True}


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
