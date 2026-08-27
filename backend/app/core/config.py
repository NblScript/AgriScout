"""应用配置：环境变量驱动，开发/生产零代码切换。"""
from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_name: str = "AgriScout"
    version: str = "0.1.0"
    environment: str = "dev"

    # 开发期默认 SQLite；生产切换 PostgreSQL(+PostGIS)
    database_url: str = "sqlite:///./agriscout.db"

    # 照片本地存储目录（生产换对象存储只改 Storage 实现）
    media_dir: str = "./media"

    # 逗号分隔的允许跨域来源
    cors_origins: str = "http://localhost:5173"

    # 识别引擎：placeholder 颜色统计 | yolo 麦穗检测（需 requirements-ml.txt + 模型文件）
    analyzer_backend: str = "placeholder"
    yolo_model_path: str = "./models/wheat-yolo-v1.pt"

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
