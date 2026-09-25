import logging
import os
import sys
from contextlib import asynccontextmanager
from urllib.parse import urlparse

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

_backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _backend_dir not in sys.path:
    sys.path.insert(0, _backend_dir)

from api.logging_config import setup_concurrent_logging
from config import settings

setup_concurrent_logging()

logger = logging.getLogger(__name__)

from api.routers import (
    configuration_router,
    files_router,
    cost_router,
    credits_router,
    models_check_router,
    health_router,
    pipelines_router,
    sandbox_router,
    sessions_router,
    stages_router,
    workflow_router,
)

DEFAULT_CORS_ORIGINS = ["http://127.0.0.1:3000", "http://localhost:3000"]


def _cors_origins() -> list[str]:
    configured = []
    for raw_origin in os.getenv("XYQ_CORS_ORIGINS", "").split(","):
        origin = raw_origin.strip().rstrip("/")
        parsed = urlparse(origin)
        if (
            parsed.scheme.lower() in {"http", "https"}
            and parsed.netloc
            and not parsed.path
            and not parsed.params
            and not parsed.query
            and not parsed.fragment
        ):
            configured.append(origin)
    return list(dict.fromkeys(DEFAULT_CORS_ORIGINS + configured))


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Lilovideo API")
    logger.info("Code directory mounted at /code: %s", settings.CODE_DIR)
    yield
    logger.info("Lilovideo API shutdown complete")


app = FastAPI(title="Lilovideo", version="2.0.0", lifespan=lifespan)

cors_origins = _cors_origins()
app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
logger.info("CORS enabled for origins: %s", cors_origins)

os.makedirs(settings.CODE_DIR, exist_ok=True)
app.mount("/code", StaticFiles(directory=settings.CODE_DIR), name="code")

app.include_router(health_router)
app.include_router(cost_router)
app.include_router(credits_router)
app.include_router(models_check_router)
app.include_router(files_router)
app.include_router(workflow_router)
app.include_router(sessions_router)
app.include_router(stages_router)
app.include_router(sandbox_router)
app.include_router(pipelines_router)
app.include_router(configuration_router)
logger.info("API routers registered")


# ── 单端口模式：把构建好的前端交给后端一起托管 ──────────────────────────
#
# 背景：前端原本靠 `rewrites()` 把 30 条 `/api/*` 逐条代理到后端，而这套代理
# 漏配过**三次**（/api/cost/*、/api/credits/*、/api/models/*），症状都是
# 「直连后端 200、经前端 404」，排查时极易误判成后端问题。
#
# 把前端静态产物挂到同一个端口之后，前端与后端**同源**：
#   - 一条代理规则都不需要，那一整类问题从根上消失
#   - 没有 CORS、没有第二个端口、运行时不需要 Node 进程
#   - 用户只需要记住一个地址
#
# 挂载必须放在**所有路由之后**：Starlette 按注册顺序匹配，
# 先注册的 /api/* 才能优先命中，否则会被这个兜底挂载吃掉。
#
# 前端没构建过（没有 out/）就退回 JSON 根路径，并写清怎么构建——
# 不要让人对着一个 JSON 猜为什么没有界面。
_FRONTEND_DIST = os.path.join(os.path.dirname(_backend_dir), "frontend", "out")

if os.path.isdir(_FRONTEND_DIST) and os.path.isfile(
    os.path.join(_FRONTEND_DIST, "index.html")
):
    app.mount(
        "/",
        StaticFiles(directory=_FRONTEND_DIST, html=True),
        name="frontend",
    )
    logger.info("前端已挂载（单端口模式）：%s", _FRONTEND_DIST)
else:

    @app.get("/")
    async def root():
        return {
            "service": "Lilovideo",
            "version": "2.0.0",
            "health": "/api/health",
            "frontend": {
                "built": False,
                "message": "前端尚未构建，因此现在只能看到 API；构建后可在这同一个端口访问界面。",
                "how_to_build": "cd src/frontend && NEXT_OUTPUT=export npm run build，然后重启后端",
            },
        }

