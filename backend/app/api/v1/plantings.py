"""Planting 种植记录管理 CRUD（含 field_id/crop_id 过滤）。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.db import get_db
from app.models import Crop, Field, Planting
from app.schemas.planting import PlantingCreate, PlantingOut, PlantingUpdate

router = APIRouter(prefix="/plantings", tags=["plantings"])


def _load_stmt():
    return select(Planting).options(
        selectinload(Planting.field), selectinload(Planting.crop)
    )


@router.get("", response_model=list[PlantingOut])
def list_plantings(
    field_id: int | None = None,
    crop_id: int | None = None,
    status: str | None = None,
    db: Session = Depends(get_db),
):
    stmt = _load_stmt()
    if field_id is not None:
        stmt = stmt.where(Planting.field_id == field_id)
    if crop_id is not None:
        stmt = stmt.where(Planting.crop_id == crop_id)
    if status is not None:
        stmt = stmt.where(Planting.status == status)
    return list(db.scalars(stmt.order_by(Planting.id)).all())


@router.post("", response_model=PlantingOut, status_code=201)
def create_planting(payload: PlantingCreate, db: Session = Depends(get_db)):
    if db.get(Field, payload.field_id) is None:
        raise HTTPException(status_code=404, detail=f"地块不存在：field_id={payload.field_id}")
    if db.get(Crop, payload.crop_id) is None:
        raise HTTPException(status_code=404, detail=f"作物不存在：crop_id={payload.crop_id}")
    obj = Planting(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/{planting_id}", response_model=PlantingOut)
def get_planting(planting_id: int, db: Session = Depends(get_db)):
    obj = db.scalars(_load_stmt().where(Planting.id == planting_id)).first()
    if obj is None:
        raise HTTPException(status_code=404, detail="种植记录不存在")
    return obj


@router.patch("/{planting_id}", response_model=PlantingOut)
def update_planting(planting_id: int, payload: PlantingUpdate, db: Session = Depends(get_db)):
    obj = db.scalars(_load_stmt().where(Planting.id == planting_id)).first()
    if obj is None:
        raise HTTPException(status_code=404, detail="种植记录不存在")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(obj, key, value)
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{planting_id}", status_code=204)
def delete_planting(planting_id: int, db: Session = Depends(get_db)):
    obj = db.get(Planting, planting_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="种植记录不存在")
    db.delete(obj)
    db.commit()
