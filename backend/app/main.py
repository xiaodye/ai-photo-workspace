import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress

from fastapi import APIRouter, FastAPI, HTTPException, Request
from fastapi.exception_handlers import request_validation_exception_handler
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse

from app import storage
from app.config import get_settings
from app.credentials import ModelCredentialsUnavailable
from app.edits import segment
from app.queue import close_queue
from app.routers import (
    assets,
    auth,
    batches,
    events,
    health,
    model_settings,
    runs,
    sessions,
)

logger = logging.getLogger(__name__)

settings = get_settings()

# SAM 会话闲置回收的检查间隔，远小于 TTL 即可，不必精确
_REAP_INTERVAL = 60.0


async def _reap_idle_segments() -> None:
    """周期性释放闲置的点选会话，避免 SAM 的峰值内存长期占着不放。"""
    while True:
        await asyncio.sleep(_REAP_INTERVAL)
        try:
            await asyncio.to_thread(segment.release_idle)
        except Exception:
            # 回收失败不应影响服务本身，下一轮再试
            logger.exception("释放点选会话失败")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    await asyncio.to_thread(storage.ensure_bucket)
    reaper = asyncio.create_task(_reap_idle_segments())
    try:
        yield
    finally:
        reaper.cancel()
        with suppress(asyncio.CancelledError):
            await reaper
    await close_queue()


app = FastAPI(
    title="AI 营销素材工作台",
    docs_url="/api/docs",
    openapi_url="/api/openapi.json",
    lifespan=lifespan,
)


@app.exception_handler(ModelCredentialsUnavailable)
async def credentials_unavailable(_: Request, exc: ModelCredentialsUnavailable) -> JSONResponse:
    """模型凭据缺失或加密不可用时，返回可直接展示给用户的提示。"""
    return JSONResponse(status_code=exc.status_code, content={"detail": str(exc)})


@app.exception_handler(RequestValidationError)
async def validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
    """模型设置接口会收到密钥，校验失败时只回固定文案，不回显请求内容。"""
    if request.url.path == "/api/model-settings":
        return JSONResponse(
            status_code=422, content={"detail": "设置参数格式不正确，请检查 Key 与模型名称"}
        )
    return await request_validation_exception_handler(request, exc)


api = APIRouter(prefix="/api")
api.include_router(health.router)
api.include_router(auth.router)
api.include_router(model_settings.router)
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
