"""API v1 路由聚合。所有业务路由统一挂认证插槽依赖（基线 B4）。"""
from fastapi import APIRouter, Depends

from app.api.v1 import crops, devices, fields, health, plantings
from app.core.deps import get_current_user

api_router = APIRouter(dependencies=[Depends(get_current_user)])
api_router.include_router(health.router)
api_router.include_router(fields.router)
api_router.include_router(crops.router)
api_router.include_router(devices.router)
api_router.include_router(plantings.router)
