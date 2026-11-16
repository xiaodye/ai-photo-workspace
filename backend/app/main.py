import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import APIRouter, FastAPI, HTTPException
from fastapi.responses import FileResponse

from app import storage
from app.config import get_settings
from app.queue import close_queue
from app.routers import assets, auth, batches, events, health, runs, sessions

settings = get_settings()


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await asyncio.to_thread(storage.ensure_bucket)
    yield
    await close_queue()


app = FastAPI(
    title="AI 修图智能体",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)

api = APIRouter(prefix="/api")
api.include_router(health.router)
api.include_router(auth.router)
api.include_router(assets.router)
api.include_router(runs.router)
api.include_router(sessions.router)
api.include_router(batches.router)
app.include_router(api)

# SSE 不挂在 /api 下，便于反向代理单独关闭缓冲
app.include_router(events.router)

# 生产环境下前端与 API 同源，静态产物由本服务托管；开发环境走 Vite dev proxy。
# 前端使用 BrowserRouter（history 模式），刷新 /editor/xxx 这类路由时浏览器会真实请求该路径，
# 因此非静态文件、非 API 的路径需要回退到 index.html，交给前端路由解析。
if settings.frontend_dist.is_dir():
    _frontend_root = settings.frontend_dist.resolve()
    _index_file = _frontend_root / "index.html"

    @app.get("/{full_path:path}", include_in_schema=False)
    async def serve_frontend(full_path: str) -> FileResponse:
        # API 与 SSE 的未知路径保持 JSON 404，不要被前端兜底吞掉
        if full_path in {"api", "events"} or full_path.startswith(("api/", "events/")):
            raise HTTPException(status_code=404)

        candidate = (_frontend_root / full_path).resolve()
        if candidate.is_file() and candidate.is_relative_to(_frontend_root):
            return FileResponse(candidate)

        # 形如 assets/index-xxx.js 的资源缺失时仍返回 404，
        # 避免把 index.html 当作 JS/CSS 返回，导致浏览器报语法错误
        if "." in full_path.rsplit("/", 1)[-1]:
            raise HTTPException(status_code=404)

        return FileResponse(_index_file)
