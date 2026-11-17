"""用户级模型设置：凭据解析、准入判断与保存校验。"""

import uuid

import httpx
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.credentials import (
    ModelCredentials,
    ModelCredentialsUnavailable,
    decrypt_key,
    encrypt_key,
    hint_of,
)
from app.events import redis_client
from app.models import User
from app.schemas.model_settings import ModelDefaults, ModelSettingsIn, ModelSettingsOut

MISSING_KEY = "尚未配置模型 API Key，请先在「模型设置」中填写自己的 Key"

_VERIFY_PATH = "/compatible-mode/v1/chat/completions"
_VERIFY_TIMEOUT = 20.0
_VERIFY_COOLDOWN = 20
# 批处理里只有这几个步骤会调用云端模型，其余步骤纯本地执行
_BATCH_CLOUD_OPS = frozenset({"replace_background", "upscale_image", "expand_canvas"})


def needs_model(tool: str, params: dict | None) -> bool:
    """判断一次工具调用是否需要云端模型。"""
    if tool == "batch_process":
        operations = (params or {}).get("operations") or []
        return any(operation.get("tool") in _BATCH_CLOUD_OPS for operation in operations)

    from app.tools import spec_of

    return spec_of(tool).needs_model


def platform_fallback_enabled() -> bool:
    """平台 Key 兜底必须显式开启，公网部署保持关闭。"""
    settings = get_settings()
    return bool(settings.allow_platform_key_fallback and settings.dashscope_api_key.strip())


def credentials_of(user: User) -> ModelCredentials | None:
    """把账号记录还原成调用凭据，未配置时返回 None。"""
    if not user.model_api_key_encrypted:
        return None
    settings = get_settings()
    return ModelCredentials(
        api_key=decrypt_key(user.model_api_key_encrypted),
        planner_model=user.planner_model or settings.planner_model,
        text_to_image_model=user.text_to_image_model or settings.text_to_image_model,
        image_edit_model=user.image_edit_model or settings.image_edit_model,
        base_url=settings.dashscope_base_url,
    )


def platform_credentials() -> ModelCredentials | None:
    """兜底凭据，仅当维护者显式开启且配置了平台 Key 时可用。"""
    if not platform_fallback_enabled():
        return None
    settings = get_settings()
    return ModelCredentials(
        api_key=settings.dashscope_api_key.strip(),
        planner_model=settings.planner_model,
        text_to_image_model=settings.text_to_image_model,
        image_edit_model=settings.image_edit_model,
        base_url=settings.dashscope_base_url,
        platform=True,
    )


async def load(session: AsyncSession, user_id: uuid.UUID) -> User:
    """读取账号记录，供任务执行时按归属解析凭据。"""
    user = await session.get(User, user_id)
    if user is None:
        raise ModelCredentialsUnavailable("账号不存在，请重新登录", 401)
    return user


async def require(session: AsyncSession, user_id: uuid.UUID) -> ModelCredentials:
    """解析任务所属账号的凭据；没有可用凭据就明确拒绝，不做隐式降级。"""
    credentials = credentials_of(await load(session, user_id)) or platform_credentials()
    if credentials is None:
        raise ModelCredentialsUnavailable(MISSING_KEY, 403)
    return credentials


def read(user: User) -> ModelSettingsOut:
    """返回脱敏配置，Key 本身不会离开服务端。"""
    settings = get_settings()
    configured = bool(user.model_api_key_encrypted)
    fallback = platform_fallback_enabled()
    return ModelSettingsOut(
        configured=configured,
        platform_fallback=fallback,
        usable=configured or fallback,
        key_hint=user.model_api_key_hint if configured else None,
        planner_model=user.planner_model if configured else None,
        text_to_image_model=user.text_to_image_model if configured else None,
        image_edit_model=user.image_edit_model if configured else None,
        defaults=ModelDefaults(
            planner_model=settings.planner_model,
            text_to_image_model=settings.text_to_image_model,
            image_edit_model=settings.image_edit_model,
        ),
    )


async def save(session: AsyncSession, user: User, payload: ModelSettingsIn) -> None:
    """验证并保存配置；验证失败时原配置保持不变。"""
    key = payload.api_key.get_secret_value() if payload.api_key else None

    if key is not None:
        # 先确认主密钥可用，避免花了验证请求才发现存不进去
        encrypted = encrypt_key(key)
        if payload.verify:
            await _guard_verify(user.id)
            await verify_key(key, payload.planner_model)
        user.model_api_key_encrypted = encrypted
        user.model_api_key_hint = hint_of(key)
    elif not user.model_api_key_encrypted:
        raise ModelCredentialsUnavailable("请先填写你自己的模型 API Key", 422)

    user.planner_model = payload.planner_model
    user.text_to_image_model = payload.text_to_image_model
    user.image_edit_model = payload.image_edit_model
    await session.commit()


async def remove(session: AsyncSession, user: User) -> None:
    """删除本人的模型配置，素材与编辑历史不受影响。"""
    user.model_api_key_encrypted = None
    user.model_api_key_hint = None
    user.planner_model = None
    user.text_to_image_model = None
    user.image_edit_model = None
    await session.commit()


async def _guard_verify(user_id: uuid.UUID) -> None:
    """限制验证频率，避免有人拿这里当任意请求代理。"""
    allowed = await redis_client().set(
        f"model-verify:{user_id}", "1", nx=True, ex=_VERIFY_COOLDOWN
    )
    if not allowed:
        raise ModelCredentialsUnavailable("验证过于频繁，请稍后再试", 429)


async def verify_key(key: str, model: str) -> None:
    """用一次极短请求确认 Key 与规划模型可用，不重试。"""
    settings = get_settings()
    payload = {
        "model": model,
        "messages": [{"role": "user", "content": "hi"}],
        "max_tokens": 1,
        "stream": False,
    }
    try:
        async with httpx.AsyncClient(timeout=_VERIFY_TIMEOUT) as client:
            response = await client.post(
                f"{settings.dashscope_base_url}{_VERIFY_PATH}",
                headers={"Authorization": f"Bearer {key}"},
                json=payload,
            )
    except httpx.TimeoutException as exc:
        raise ModelCredentialsUnavailable("验证请求超时，配置未保存，请稍后重试", 504) from exc
    except httpx.HTTPError as exc:
        raise ModelCredentialsUnavailable("暂时无法连接模型服务，配置未保存", 502) from exc

    if response.status_code in (httpx.codes.UNAUTHORIZED, httpx.codes.FORBIDDEN):
        raise ModelCredentialsUnavailable("Key 无效，或没有所填规划模型的访问权限", 422)
    if response.status_code == httpx.codes.TOO_MANY_REQUESTS:
        raise ModelCredentialsUnavailable("模型服务限流或账户额度不足，请检查后再试", 429)
    if response.status_code != httpx.codes.OK:
        raise ModelCredentialsUnavailable("Key 验证失败，请检查 Key 与规划模型名称", 422)

    try:
        body = response.json()
    except ValueError as exc:
        raise ModelCredentialsUnavailable("模型服务返回了无法识别的验证结果", 502) from exc
    if not body.get("choices"):
        raise ModelCredentialsUnavailable("模型服务未返回有效验证结果，配置未保存", 502)
