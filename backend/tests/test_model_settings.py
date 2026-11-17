import io
import uuid

import httpx
import pytest
from PIL import Image
from sqlalchemy import select

from app.config import get_settings
from app.credentials import ModelCredentialsUnavailable, decrypt_key
from app.db import SessionFactory
from app.models import ToolRun, User
from app.providers import current_credentials
from app.services import model_settings as settings_service
from app.tasks.tools import run_tool

MODELS = {
    "planner_model": "qwen-plus",
    "text_to_image_model": "qwen-image-test",
    "image_edit_model": "qwen-edit-test",
}

KEY = "sk-test-user-key-1234"
OTHER_KEY = "sk-test-other-key-5678"


@pytest.fixture
def verified(monkeypatch):
    """替换真实 Key 验证与限流，测试不发任何外部请求。"""
    calls: list[tuple[str, str]] = []

    async def verify(key: str, model: str) -> None:
        calls.append((key, model))

    async def guard(_: uuid.UUID) -> None:
        return None

    monkeypatch.setattr(settings_service, "verify_key", verify)
    monkeypatch.setattr(settings_service, "_guard_verify", guard)
    return calls


async def register(client: httpx.AsyncClient, account: dict[str, str]) -> uuid.UUID:
    response = await client.post("/api/auth/register", json=account)
    assert response.status_code == 201
    return uuid.UUID(response.json()["id"])


async def save(
    client: httpx.AsyncClient, key: str | None = KEY, **overrides: object
) -> httpx.Response:
    body: dict[str, object] = {**MODELS, **overrides, "verify": True}
    if key is not None:
        body["api_key"] = key
    return await client.put("/api/model-settings", json=body)


async def stored_key(user_id: uuid.UUID) -> str | None:
    async with SessionFactory() as session:
        return (await session.get(User, user_id)).model_api_key_encrypted


async def test_settings_require_login(client: httpx.AsyncClient):
    assert (await client.get("/api/model-settings")).status_code == 401
    assert (await client.put("/api/model-settings", json=MODELS)).status_code == 401
    assert (await client.delete("/api/model-settings")).status_code == 401


async def test_save_encrypts_key_and_never_returns_it(
    client: httpx.AsyncClient, credentials, verified
):
    user_id = await register(client, credentials)

    response = await save(client)

    assert response.status_code == 200, response.text
    body = response.json()
    assert body["configured"] is True
    assert body["usable"] is True
    assert body["key_hint"] == "****1234"
    assert body["planner_model"] == MODELS["planner_model"]
    assert KEY not in response.text

    encrypted = await stored_key(user_id)
    assert encrypted is not None
    assert KEY not in encrypted
    assert decrypt_key(encrypted) == KEY
    assert verified == [(KEY, MODELS["planner_model"])]


async def test_models_only_update_keeps_saved_key(client: httpx.AsyncClient, credentials, verified):
    user_id = await register(client, credentials)
    assert (await save(client)).status_code == 200
    encrypted = await stored_key(user_id)

    response = await save(client, key=None, planner_model="qwen-max")

    assert response.status_code == 200
    assert response.json()["planner_model"] == "qwen-max"
    assert await stored_key(user_id) == encrypted
    assert len(verified) == 1


async def test_failed_verification_keeps_previous_config(
    client: httpx.AsyncClient, credentials, verified, monkeypatch
):
    user_id = await register(client, credentials)
    assert (await save(client)).status_code == 200
    encrypted = await stored_key(user_id)

    async def reject(key: str, model: str) -> None:
        raise ModelCredentialsUnavailable("Key 无效，或没有所填规划模型的访问权限", 422)

    monkeypatch.setattr(settings_service, "verify_key", reject)

    response = await save(client, key=OTHER_KEY)

    assert response.status_code == 422
    assert await stored_key(user_id) == encrypted
    assert (await client.get("/api/model-settings")).json()["key_hint"] == "****1234"


async def test_invalid_key_shape_is_rejected_without_echo(
    client: httpx.AsyncClient, credentials, verified
):
    await register(client, credentials)

    response = await save(client, key="sk live should not leak")

    assert response.status_code == 422
    # 校验失败不能把提交的 Key 回显在响应里
    assert "should not leak" not in response.text
    assert verified == []


async def test_delete_clears_only_model_settings(client: httpx.AsyncClient, credentials, verified):
    await register(client, credentials)
    assert (await save(client)).status_code == 200

    assert (await client.delete("/api/model-settings")).status_code == 204

    body = (await client.get("/api/model-settings")).json()
    assert body["configured"] is False
    assert body["key_hint"] is None
    assert (await client.get("/api/auth/me")).status_code == 200


async def test_missing_master_key_fails_closed(
    client: httpx.AsyncClient, credentials, verified, monkeypatch
):
    await register(client, credentials)
    monkeypatch.setattr(get_settings(), "credential_encryption_key", "")

    response = await save(client)

    assert response.status_code == 503
    assert verified == []
    assert (await client.get("/api/model-settings")).json()["configured"] is False


async def test_no_platform_fallback_without_own_key(
    client: httpx.AsyncClient, credentials, monkeypatch
):
    user_id = await register(client, credentials)
    settings = get_settings()
    monkeypatch.setattr(settings, "allow_platform_key_fallback", False)
    monkeypatch.setattr(settings, "dashscope_api_key", "sk-platform-should-not-be-used")

    response = await client.post("/api/generations", json={"prompt": "一个白色马克杯"})

    assert response.status_code == 403
    assert "模型设置" in response.json()["detail"]
    # 没有凭据时不应留下排队任务
    async with SessionFactory() as session:
        queued = await session.scalars(select(ToolRun).where(ToolRun.user_id == user_id))
    assert queued.all() == []


async def test_platform_fallback_is_reported_separately(client: httpx.AsyncClient, credentials):
    await register(client, credentials)

    body = (await client.get("/api/model-settings")).json()

    assert body["configured"] is False
    assert body["platform_fallback"] is True
    assert body["usable"] is True
    assert body["key_hint"] is None


async def test_each_account_uses_its_own_credentials(
    client: httpx.AsyncClient, credentials, other_credentials, verified, monkeypatch
):
    from app.providers.mock import MockImageProvider

    observed: list[tuple[str, str]] = []
    original = MockImageProvider.generate

    async def generate(self, request, on_progress=None):
        credentials_used = current_credentials()
        observed.append((credentials_used.api_key, credentials_used.text_to_image_model))
        return await original(self, request, on_progress)

    monkeypatch.setattr(MockImageProvider, "generate", generate)

    for account, key, model in (
        (credentials, KEY, "image-a"),
        (other_credentials, OTHER_KEY, "image-b"),
    ):
        await register(client, account)
        assert (
            await save(client, key=key, text_to_image_model=model)
        ).status_code == 200
        created = await client.post("/api/generations", json={"prompt": "马克杯", "count": 1})
        assert created.status_code == 202, created.text
        run_id = uuid.UUID(created.json()["id"])
        async with SessionFactory() as session:
            run = await session.get(ToolRun, run_id)
            # 密钥只存在于内存作用域，不进入任务参数
            assert key not in str(run.params)
        await run_tool({}, run_id)
        assert (await client.get(f"/api/runs/{run_id}")).json()["status"] == "succeeded"
        await client.post("/api/auth/logout")

    assert observed == [(KEY, "image-a"), (OTHER_KEY, "image-b")]


async def test_batch_local_only_steps_need_no_key(
    client: httpx.AsyncClient, credentials, monkeypatch
):
    await register(client, credentials)
    settings = get_settings()
    monkeypatch.setattr(settings, "allow_platform_key_fallback", False)
    monkeypatch.setattr(settings, "dashscope_api_key", "")

    upload = await client.post(
        "/api/assets", files={"file": ("cup.png", _png(), "image/png")}
    )
    assert upload.status_code == 201, upload.text
    response = await client.post(
        "/api/batches",
        json={
            "asset_ids": [upload.json()["id"]],
            "operations": [{"tool": "adjust_image", "params": {"brightness": 0.1}}],
            "formats": ["png"],
        },
    )

    assert response.status_code == 202, response.text


def _png() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (64, 64), (200, 180, 160)).save(buffer, format="PNG")
    return buffer.getvalue()
