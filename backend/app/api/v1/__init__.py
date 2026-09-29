"""API v1 路由聚合。所有路由统一挂认证依赖（基线 B4 → 决策 D15），公开白名单与角色策略见 core/deps.py。"""
from fastapi import APIRouter, Depends

from app.api.v1 import (
    advices,
    agent,
    annotations,
    auth,
    capture_points,
    crops,
    device_protocol,
    devices,
    fields,
    health,
    ingest,
    patrols,
    plantings,
    reports,
    rule_revisions,
    rules,
    software_loop,
    stats,
    users,
)
from app.core.deps import get_current_user

api_router = APIRouter(dependencies=[Depends(get_current_user)])
api_router.include_router(health.router)
api_router.include_router(auth.router)
api_router.include_router(users.router)
# Protocol paths such as /devices/register must precede /devices/{device_id}.
api_router.include_router(device_protocol.router)
api_router.include_router(fields.router)
api_router.include_router(crops.router)
api_router.include_router(devices.router)
api_router.include_router(plantings.router)
api_router.include_router(patrols.router)
api_router.include_router(capture_points.router)
api_router.include_router(ingest.router)
api_router.include_router(rules.router)
api_router.include_router(advices.router)
api_router.include_router(annotations.router)
api_router.include_router(stats.router)
api_router.include_router(reports.router)
api_router.include_router(agent.router)
api_router.include_router(rule_revisions.router)
api_router.include_router(software_loop.router)
