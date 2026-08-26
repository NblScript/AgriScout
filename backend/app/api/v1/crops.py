"""Crop 作物管理 CRUD。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import Crop
from app.schemas.crop import CropCreate, CropOut, CropUpdate

router = APIRouter(prefix="/crops", tags=["crops"])


@router.get("", response_model=list[CropOut])
def list_crops(db: Session = Depends(get_db)):
    return list(db.scalars(select(Crop).order_by(Crop.id)).all())


@router.post("", response_model=CropOut, status_code=201)
def create_crop(payload: CropCreate, db: Session = Depends(get_db)):
    if db.scalar(select(Crop).where(Crop.name == payload.name)):
        raise HTTPException(status_code=409, detail=f"作物已存在：{payload.name}")
    obj = Crop(**payload.model_dump())
    db.add(obj)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="作物创建失败：唯一约束冲突")
    db.refresh(obj)
    return obj


@router.get("/{crop_id}", response_model=CropOut)
def get_crop(crop_id: int, db: Session = Depends(get_db)):
    obj = db.get(Crop, crop_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="作物不存在")
    return obj


@router.patch("/{crop_id}", response_model=CropOut)
def update_crop(crop_id: int, payload: CropUpdate, db: Session = Depends(get_db)):
    obj = db.get(Crop, crop_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="作物不存在")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(obj, key, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="作物更新失败：唯一约束冲突")
    db.refresh(obj)
    return obj


@router.delete("/{crop_id}", status_code=204)
def delete_crop(crop_id: int, db: Session = Depends(get_db)):
    obj = db.get(Crop, crop_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="作物不存在")
    db.delete(obj)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="该作物被种植记录引用，请先删除对应种植记录")
