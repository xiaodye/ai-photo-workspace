from fastapi import APIRouter, status

from app.db import SessionDep
from app.deps import CurrentUser
from app.schemas.model_settings import ModelSettingsIn, ModelSettingsOut
from app.services import model_settings

router = APIRouter(prefix="/model-settings", tags=["model-settings"])


@router.get("")
async def read(user: CurrentUser) -> ModelSettingsOut:
    """查看当前账号的脱敏模型设置。"""
    return model_settings.read(user)


@router.put("")
async def save(
    payload: ModelSettingsIn, user: CurrentUser, session: SessionDep
) -> ModelSettingsOut:
    """验证并保存当前账号自己的模型 Key 与模型名。"""
    await model_settings.save(session, user, payload)
    return model_settings.read(user)


@router.delete("", status_code=status.HTTP_204_NO_CONTENT)
async def remove(user: CurrentUser, session: SessionDep) -> None:
    """删除当前账号的模型配置。"""
    await model_settings.remove(session, user)
