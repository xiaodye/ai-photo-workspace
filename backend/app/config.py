from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT_DIR = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=ROOT_DIR / ".env", env_file_encoding="utf-8", extra="ignore"
    )

    app_env: str = "development"
    api_port: int = 7302

    database_url: str = "postgresql+asyncpg://retouch:retouch_dev@localhost:7311/retouch"
    redis_url: str = "redis://localhost:7312"

    s3_endpoint: str = "http://localhost:7313"
    # 浏览器打开签名 URL 的地址；空则与 s3_endpoint 相同
    s3_public_endpoint: str = ""
    s3_access_key: str = "retouch"
    s3_secret_key: str = "retouch_dev"
    s3_bucket: str = "retouch"
    # 签名 URL 有效期，秒
    s3_url_ttl: int = 900

    # HS256 要求密钥不短于 32 字节
    jwt_secret: str = "dev-only-secret-please-change-in-production"
    jwt_ttl_hours: int = 24

    # image provider: mock | dashscope
    image_provider: str = "mock"
    # 平台 Key 只在显式开启兜底时使用，公网部署保持关闭，避免访客消耗维护者额度
    dashscope_api_key: str = ""
    allow_platform_key_fallback: bool = False
    # 业务空间专属域名为 https://{WorkspaceId}.cn-beijing.maas.aliyuncs.com
    dashscope_base_url: str = "https://dashscope.aliyuncs.com"
    # 用户未指定模型名时的默认值，同时用于界面表单预填
    text_to_image_model: str = "qwen-image-3.0-pro"
    image_edit_model: str = "qwen-image-edit-max"
    planner_model: str = "qwen-plus"
    # 加密用户 Key 的 Fernet 主密钥；API 与 Worker 必须一致，留空则无法保存或使用用户 Key
    credential_encryption_key: str = ""
    # auto：有 rembg 用 rembg，否则四角抠图；测试强制 corner 以免下载模型
    matting_provider: str = "auto"
    # rembg 权重名：isnet-general-use 约 180MB、峰值约 1GB；bria-rmbg 效果更好但要 8GB 以上内存
    matting_model: str = "isnet-general-use"
    # auto：有 rapidocr 则识别文字层；none 跳过；测试强制 none
    ocr_provider: str = "auto"

    @property
    def is_production(self) -> bool:
        return self.app_env == "production"

    @property
    def frontend_dist(self) -> Path:
        return ROOT_DIR / "client" / "dist"


@lru_cache
def get_settings() -> Settings:
    return Settings()
