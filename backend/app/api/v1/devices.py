"""Device 载体管理 CRUD。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import Device
from app.schemas.device import DeviceCreate, DeviceOut, DeviceUpdate

router = APIRouter(prefix="/devices", tags=["devices"])


@router.get("", response_model=list[DeviceOut])
def list_devices(db: Session = Depends(get_db)):
    return list(db.scalars(select(Device).order_by(Device.id)).all())


@router.post("", response_model=DeviceOut, status_code=201)
def create_device(payload: DeviceCreate, db: Session = Depends(get_db)):
    if db.scalar(select(Device).where(Device.code == payload.code)):
        raise HTTPException(status_code=409, detail=f"设备编号已存在：{payload.code}")
    obj = Device(**payload.model_dump())
    db.add(obj)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="设备创建失败：唯一约束冲突")
    db.refresh(obj)
    return obj


@router.get("/{device_id}", response_model=DeviceOut)
def get_device(device_id: int, db: Session = Depends(get_db)):
    obj = db.get(Device, device_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="设备不存在")
    return obj


@router.patch("/{device_id}", response_model=DeviceOut)
def update_device(device_id: int, payload: DeviceUpdate, db: Session = Depends(get_db)):
    obj = db.get(Device, device_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="设备不存在")
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(obj, key, value)
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{device_id}", status_code=204)
def delete_device(device_id: int, db: Session = Depends(get_db)):
    obj = db.get(Device, device_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="设备不存在")
    db.delete(obj)
    db.commit()
