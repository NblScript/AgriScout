"""Field 地块管理 CRUD。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import Field
from app.schemas.field import FieldCreate, FieldOut, FieldUpdate

router = APIRouter(prefix="/fields", tags=["fields"])


@router.get("", response_model=list[FieldOut])
def list_fields(db: Session = Depends(get_db)):
    return list(db.scalars(select(Field).order_by(Field.id)).all())


@router.post("", response_model=FieldOut, status_code=201)
def create_field(payload: FieldCreate, db: Session = Depends(get_db)):
    if db.scalar(select(Field).where(Field.name == payload.name)):
        raise HTTPException(status_code=409, detail=f"地块名称已存在：{payload.name}")
    obj = Field(**payload.model_dump())
    db.add(obj)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="地块创建失败：唯一约束冲突")
    db.refresh(obj)
    return obj


@router.get("/{field_id}", response_model=FieldOut)
def get_field(field_id: int, db: Session = Depends(get_db)):
    obj = db.get(Field, field_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="地块不存在")
    return obj


@router.patch("/{field_id}", response_model=FieldOut)
def update_field(field_id: int, payload: FieldUpdate, db: Session = Depends(get_db)):
    obj = db.get(Field, field_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="地块不存在")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(obj, key, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="地块更新失败：唯一约束冲突")
    db.refresh(obj)
    return obj


@router.delete("/{field_id}", status_code=204)
def delete_field(field_id: int, db: Session = Depends(get_db)):
    obj = db.get(Field, field_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="地块不存在")
    db.delete(obj)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="该地块下存在种植记录，请先删除对应种植记录")
