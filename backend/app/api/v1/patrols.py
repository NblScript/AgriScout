"""Patrol 巡检任务查询。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from app.core.db import get_db
from app.models import Patrol
from app.schemas.capture_point import PatrolDetailOut, PatrolOut
from app.schemas.common import Page

router = APIRouter(prefix="/patrols", tags=["patrols"])


def _apply_filters(stmt, field_id: int | None, status: str | None, analysis_status: str | None):
    if field_id is not None:
        stmt = stmt.where(Patrol.field_id == field_id)
    if status is not None:
        stmt = stmt.where(Patrol.status == status)
    if analysis_status is not None:
        stmt = stmt.where(Patrol.analysis_status == analysis_status)
    return stmt


@router.get("", response_model=Page[PatrolOut])
def list_patrols(
    field_id: int | None = None,
    status: str | None = None,
    analysis_status: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    base = _apply_filters(select(Patrol), field_id, status, analysis_status)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    rows = db.scalars(base.order_by(Patrol.id.desc()).offset(skip).limit(limit)).all()
    return Page(items=list(rows), total=total, skip=skip, limit=limit)


@router.get("/{patrol_id}", response_model=PatrolDetailOut)
def get_patrol(patrol_id: int, db: Session = Depends(get_db)):
    obj = db.scalars(
        select(Patrol)
        .options(selectinload(Patrol.field), selectinload(Patrol.device), selectinload(Patrol.capture_points))
        .where(Patrol.id == patrol_id)
    ).first()
    if obj is None:
        raise HTTPException(status_code=404, detail="巡检任务不存在")
    return obj
