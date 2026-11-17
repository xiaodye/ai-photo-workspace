from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from contextvars import ContextVar
from dataclasses import dataclass

from app.config import get_settings
from app.credentials import ModelCredentials, ModelCredentialsUnavailable
from app.providers.base import EditRequest, GenerateRequest, ImageProvider, ProviderError
from app.providers.mock import MockImageProvider

MISSING_CREDENTIALS = "尚未配置模型 API Key，请先在「模型设置」中填写自己的 Key"


@dataclass
class _Scope:
    """当前任务独占的凭据与客户端，避免认证信息跨账号复用。"""

    # 本次调用使用的凭据；纯本地工具为 None。
    credentials: ModelCredentials | None
    # 按需创建、在本作用域结束时关闭的图片服务客户端。
    provider: ImageProvider | None = None


_scope: ContextVar[_Scope | None] = ContextVar("model_scope", default=None)


def current_credentials() -> ModelCredentials:
    """读取当前调用作用域的凭据，缺失时禁止隐式回退到平台配置。"""
    scope = _scope.get()
    if scope is None or scope.credentials is None:
        raise ModelCredentialsUnavailable(MISSING_CREDENTIALS, 403)
    return scope.credentials


@asynccontextmanager
async def model_scope(credentials: ModelCredentials | None) -> AsyncIterator[None]:
    """为一次规划或工具执行隔离凭据，并在结束时释放网络连接。"""
    scope = _Scope(credentials)
    token = _scope.set(scope)
    try:
        yield
    finally:
        _scope.reset(token)
        if scope.provider is not None:
            await scope.provider.aclose()


def get_image_provider() -> ImageProvider:
    """返回当前任务作用域的图片服务实例，同一任务内复用同一客户端。"""
    scope = _scope.get()
    if scope is None or scope.credentials is None:
        raise ModelCredentialsUnavailable(MISSING_CREDENTIALS, 403)
    if scope.provider is None:
        scope.provider = _build(scope.credentials)
    return scope.provider


def _build(credentials: ModelCredentials) -> ImageProvider:
    """按配置选择实现。新增平台只需在此登记，调用方无需改动。"""
    settings = get_settings()
    name = settings.image_provider

    if name == "mock":
        # 占位图只用于本地开发，公网部署不能悄悄返回假图
        if settings.is_production:
            raise ProviderError("生产环境不能使用占位图服务，请配置 IMAGE_PROVIDER=dashscope")
        return MockImageProvider()
    if name == "dashscope":
        from app.providers.dashscope import DashScopeImageProvider

        return DashScopeImageProvider(credentials)

    raise ProviderError(f"未知的 IMAGE_PROVIDER：{name}")


def redact(message: str) -> str:
    """移除当前作用域的 Key，避免错误文案把密钥带给浏览器或日志。"""
    scope = _scope.get()
    if scope is None or scope.credentials is None:
        return message
    return message.replace(scope.credentials.api_key, "[已隐藏]")


__all__ = [
    "EditRequest",
    "GenerateRequest",
    "ImageProvider",
    "ProviderError",
    "current_credentials",
    "get_image_provider",
    "model_scope",
    "redact",
]
