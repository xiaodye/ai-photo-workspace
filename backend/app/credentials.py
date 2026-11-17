"""用户级模型凭据：加密存储、解析与脱敏。

Key 只在当前任务的调用作用域内解密，既不落盘明文，也不返回给浏览器。
"""

from dataclasses import dataclass, field

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings

HIDDEN = "[已隐藏]"
_MIN_HINT_LENGTH = 8


class ModelCredentialsUnavailable(Exception):
    """当前账号没有可用的模型凭据，消息可直接展示给用户。"""

    def __init__(self, message: str, status_code: int = 403) -> None:
        super().__init__(message)
        self.status_code = status_code


@dataclass(frozen=True)
class ModelCredentials:
    """一次模型调用所需的 Key 与模型名。"""

    # 解密后的 Key，只能在调用作用域内使用。
    api_key: str = field(repr=False)
    # 对话规划模型名称。
    planner_model: str
    # 文生图模型名称。
    text_to_image_model: str
    # 图片编辑模型名称。
    image_edit_model: str
    # 模型服务地址。
    base_url: str
    # 是否来自平台配置兜底，仅 ALLOW_PLATFORM_KEY_FALLBACK 开启时出现。
    platform: bool = False


def _cipher() -> Fernet:
    """加载部署环境中的独立加密主密钥，缺失或格式错误时拒绝服务。"""
    raw = get_settings().credential_encryption_key.strip()
    if not raw:
        raise ModelCredentialsUnavailable(
            "服务器尚未配置模型密钥加密主密钥，暂时无法保存或使用模型 Key，请联系维护者", 503
        )
    try:
        return Fernet(raw.encode())
    except (ValueError, TypeError) as exc:
        raise ModelCredentialsUnavailable(
            "服务器模型密钥加密主密钥格式不正确，请联系维护者", 503
        ) from exc


def encrypt_key(key: str) -> str:
    """加密用户 Key，供数据库持久化。"""
    return _cipher().encrypt(key.encode()).decode()


def decrypt_key(token: str) -> str:
    """解密数据库中的 Key；主密钥变更或数据损坏时明确失败，不做降级。"""
    try:
        return _cipher().decrypt(token.encode()).decode()
    except (InvalidToken, ValueError, UnicodeError) as exc:
        raise ModelCredentialsUnavailable(
            "无法读取已保存的模型 Key，请重新填写并保存，或联系维护者", 503
        ) from exc


def hint_of(key: str) -> str:
    """生成可安全展示的尾号提示。"""
    if len(key) <= _MIN_HINT_LENGTH:
        return "****"
    return f"****{key[-4:]}"


def mask(text: str, secret: str) -> str:
    """从错误文案中去掉当前 Key，避免第三方错误回显泄露认证信息。"""
    if not secret:
        return text
    return text.replace(secret, HIDDEN)
