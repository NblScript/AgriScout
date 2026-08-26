"""CapturePoint 采样点查询：分页 + 跨巡检 bbox 空间过滤（基线 B1 浮点区间查询）。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.db import get_db
from app.models import CapturePoint
from app.schemas.capture_point import CapturePointOut
from app.schemas.common import Page

router = APIRouter(prefix="/capture-points", tags=["capture-points"])


def _parse_bbox(bbox: str) -> tuple[float, float, float, float]:
    """bbox=minLng,minLat,maxLng,maxLat。"""
    parts = bbox.split(",")
    if len(parts) != 4:
        raise HTTPException(status_code=422, detail="bbox 格式应为 minLng,minLat,maxLng,maxLat")
    try:
        min_lng, min_lat, max_lng, max_lat = (float(p.strip()) for p in parts)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=f"bbox 含非数字：{exc}") from exc
    if not (-180 <= min_lng <= 180 and -180 <= max_lng <= 180):
        raise HTTPException(status_code=422, detail="bbox 经度越界")
    if not (-90 <= min_lat <= 90 and -90 <= max_lat <= 90):
        raise HTTPException(status_code=422, detail="bbox 纬度越界")
    if min_lng > max_lng or min_lat > max_lat:
        raise HTTPException(status_code=422, detail="bbox min 值不能大于 max 值")
    return min_lng, min_lat, max_lng, max_lat


@router.get("", response_model=Page[CapturePointOut])
def list_capture_points(
    patrol_id: int | None = None,
    bbox: str | None = Query(None, description="minLng,minLat,maxLng,maxLat"),
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    stmt = select(CapturePoint).options(selectinload(CapturePoint.weather))
    if patrol_id is not None:
        stmt = stmt.where(CapturePoint.patrol_id == patrol_id)
    if bbox is not None:
        min_lng, min_lat, max_lng, max_lat = _parse_bbox(bbox)
        stmt = stmt.where(
            CapturePoint.lng >= min_lng,
            CapturePoint.lng <= max_lng,
            CapturePoint.lat >= min_lat,
            CapturePoint.lat <= max_lat,
        )
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    rows = db.scalars(stmt.order_by(CapturePoint.id).offset(skip).limit(limit)).all()
    return Page(items=list(rows), total=total, skip=skip, limit=limit)
