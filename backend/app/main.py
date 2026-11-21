from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import audit  # noqa: F401  注册 audit_log 的 after_create 触发器
from .db import Base, SessionLocal, engine
from .routers import audit_log, auth, schedule, tasks, users, workers
from .seed import seed

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"  # 前端构建产物


@asynccontextmanager
async def lifespan(_: FastAPI):
    # 开发期直接 create_all；表结构稳定后（切 PostgreSQL 前）改用 Alembic 迁移
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        seed(db)
    yield


app = FastAPI(title="工作记录系统", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(schedule.router)
app.include_router(audit_log.router)
app.include_router(workers.router)
app.include_router(tasks.router)


@app.get("/api/health")
def health():
    return {"ok": True}


if STATIC_DIR.exists():
    app.mount("/assets", StaticFiles(directory=STATIC_DIR / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = STATIC_DIR / path
        if path and f.is_file() and STATIC_DIR in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(STATIC_DIR / "index.html")
