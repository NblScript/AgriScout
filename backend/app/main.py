"""AgriScout 后端入口。"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from app.api.v1 import api_router
from app.core.config import get_settings

settings = get_settings()

# 令牌签名密钥：开发环境可缺省（用开发密钥并告警），其余环境缺省即拒绝启动（决策 D15）
if settings.environment != "dev" and not settings.auth_secret:
    raise RuntimeError("非开发环境必须设置 AUTH_SECRET")

app = FastAPI(
    title=settings.app_name,
    version=settings.version,
    description="巡知（AgriScout）农田智能巡检系统后端",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origin_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 业务路由统一前缀 /api/v1；认证插槽已在 api_router 层挂载
app.include_router(api_router, prefix="/api/v1")

# 本地照片静态服务（基线 D6）：生产换对象存储时移除本行
app.mount("/media", StaticFiles(directory=settings.media_dir, check_dir=False), name="media")
