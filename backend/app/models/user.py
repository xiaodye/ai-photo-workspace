from sqlalchemy import String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import UUIDBase


class User(UUIDBase):
    """用户账号、登录凭据及本人模型配置。"""

    __tablename__ = "users"

    # 登录用户名。
    username: Mapped[str] = mapped_column(String(32), unique=True, index=True)
    # 登录密码的哈希值。
    password_hash: Mapped[str] = mapped_column(String(128))
    # 本人在模型服务申请的 Key 密文，空值表示尚未配置。
    model_api_key_encrypted: Mapped[str | None] = mapped_column(Text, default=None)
    # Key 尾号提示，只用于展示，不含完整密钥。
    model_api_key_hint: Mapped[str | None] = mapped_column(String(16), default=None)
    # 对话规划模型名称。
    planner_model: Mapped[str | None] = mapped_column(String(128), default=None)
    # 文生图模型名称。
    text_to_image_model: Mapped[str | None] = mapped_column(String(128), default=None)
    # 图片编辑模型名称。
    image_edit_model: Mapped[str | None] = mapped_column(String(128), default=None)
