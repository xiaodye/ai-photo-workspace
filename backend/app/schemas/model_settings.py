from typing import Annotated

from pydantic import BaseModel, ConfigDict, SecretStr, StringConstraints, field_validator

# 模型名来自模型服务文档，只允许常见字符，避免拼出脏数据
ModelName = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        max_length=128,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/-]*$",
    ),
]

MIN_KEY_LENGTH = 8
MAX_KEY_LENGTH = 512


class ModelSettingsIn(BaseModel):
    """保存当前账号的模型设置。"""

    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    # 待保存的 Key；留空表示沿用已保存的 Key。
    api_key: SecretStr | None = None
    # 对话规划模型。
    planner_model: ModelName
    # 文生图模型。
    text_to_image_model: ModelName
    # 图片编辑模型。
    image_edit_model: ModelName
    # 保存前是否发送一次极短请求验证 Key。
    verify: bool = True

    @field_validator("api_key")
    @classmethod
    def _check_api_key(cls, value: SecretStr | None) -> SecretStr | None:
        if value is None:
            return None
        key = value.get_secret_value().strip()
        if not MIN_KEY_LENGTH <= len(key) <= MAX_KEY_LENGTH:
            raise ValueError("密钥长度不正确")
        if any(char.isspace() for char in key):
            raise ValueError("密钥不能包含空白字符")
        return SecretStr(key)


class ModelDefaults(BaseModel):
    """界面表单的默认模型名。"""

    # 对话规划模型。
    planner_model: str
    # 文生图模型。
    text_to_image_model: str
    # 图片编辑模型。
    image_edit_model: str


class ModelSettingsOut(BaseModel):
    """脱敏后的模型设置，任何情况下都不包含完整 Key。"""

    # 当前账号是否已保存自己的 Key。
    configured: bool
    # 未配置时是否可使用平台 Key 兜底（默认关闭）。
    platform_fallback: bool
    # 当前是否可以进行模型调用。
    usable: bool
    # 已保存 Key 的尾号提示。
    key_hint: str | None = None
    # 已保存的规划模型。
    planner_model: str | None = None
    # 已保存的文生图模型。
    text_to_image_model: str | None = None
    # 已保存的图片编辑模型。
    image_edit_model: str | None = None
    # 表单预填用的默认模型名。
    defaults: ModelDefaults
