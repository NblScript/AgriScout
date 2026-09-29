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

    # 登录令牌（决策 D15）：签名密钥非 dev 环境必填；令牌有效期（小时）
    auth_secret: str = ""
    auth_token_hours: int = 12

    # 识别引擎：placeholder 颜色统计 | yolo 麦穗检测（需 requirements-ml.txt + 模型文件）
    analyzer_backend: str = "placeholder"
    yolo_model_path: str = "./models/wheat-yolo-v1.pt"  # 留空 = 不做数穗，长势沿用颜色统计
    # 条锈病图块分类模型（计划 0010，ml/train_rust.py 训练导出）；留空 = 不启用，病害信号沿用颜色统计
    disease_model_path: str = ""
    # 可训练风险模型（risk-lr-*）的模型文件目录：<目录>/<版本号>.json（训练产物，不入库）
    risk_model_dir: str = "./models"

    # LLM 建议线（OpenAI 兼容 /chat/completions，智谱/DeepSeek/通义等均可；留空=功能关闭）
    llm_api_base: str = ""
    llm_api_key: str = ""
    llm_model: str = ""

    @property
    def llm_enabled(self) -> bool:
        return bool(self.llm_api_base and self.llm_api_key and self.llm_model)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
