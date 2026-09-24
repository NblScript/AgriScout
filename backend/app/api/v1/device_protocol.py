"""采集端设备协议：注册、心跳、事件和故障注入。

故障注入只写入可回放的 ``DeviceEvent``，用于故障注入测试和状态机联调，
不把测试请求当成真实编码器、RTK、天气或急停结果。
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import Device, DeviceEvent, DeviceHeartbeat, Patrol
from app.schemas.device import DeviceOut
from app.schemas.device_protocol import (
    DeviceEventIn,
    DeviceEventOut,
    DeviceHeartbeatIn,
    DeviceHeartbeatOut,
    DeviceRegisterIn,
    FaultInjectionIn,
)

router = APIRouter(tags=["device-protocol"])

_SAFETY_EVENT_TYPES = {
    "emergency_stop",
    "watchdog_timeout",
    "low_voltage",
    "obstacle",
    "fault_injected",
}


def _device_or_404(db: Session, device_id: int) -> Device:
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="设备不存在")
    return device


def _mission_or_404(db: Session, mission_id: int) -> Patrol:
    """当前 Patrol 是任务实体；协议层保留 mission_id 命名。"""

    mission = db.get(Patrol, mission_id)
    if mission is None:
        raise HTTPException(status_code=404, detail="任务不存在")
    return mission


def _validate_mission(db: Session, mission_id: int | None, device_id: int | None) -> Patrol | None:
    mission = _mission_or_404(db, mission_id) if mission_id is not None else None
    if mission is not None and mission.device_id is not None and device_id is not None:
        if mission.device_id != device_id:
            raise HTTPException(status_code=409, detail="任务与设备不匹配")
    return mission


def _existing_heartbeat(db: Session, device_id: int, client_id: str | None) -> DeviceHeartbeat | None:
    if not client_id:
        return None
    return db.scalar(
        select(DeviceHeartbeat).where(
            DeviceHeartbeat.device_id == device_id,
            DeviceHeartbeat.client_heartbeat_id == client_id,
        )
    )


def _existing_event(db: Session, device_id: int | None, client_id: str | None) -> DeviceEvent | None:
    if not client_id:
        return None
    stmt = select(DeviceEvent).where(DeviceEvent.client_event_id == client_id)
    if device_id is None:
        stmt = stmt.where(DeviceEvent.device_id.is_(None))
    else:
        stmt = stmt.where(DeviceEvent.device_id == device_id)
    return db.scalar(stmt)


def _apply_event_status(device: Device, event_type: str, severity: str) -> None:
    """只对明确的安全事件进入维护态，不推断普通业务事件的硬件状态。"""

    if event_type in _SAFETY_EVENT_TYPES and severity in {"error", "critical"}:
        device.status = "maintenance"


@router.post("/devices/register", response_model=DeviceOut)
def register_device(payload: DeviceRegisterIn, db: Session = Depends(get_db)):
    """按设备 code 幂等注册；已登记设备更新可变描述字段。"""

    obj = db.scalar(select(Device).where(Device.code == payload.code))
    if obj is None:
        obj = Device(**payload.model_dump())
        db.add(obj)
    else:
        values = payload.model_dump(exclude_unset=True)
        for key in ("name", "type", "model", "status", "notes"):
            if key in values:
                setattr(obj, key, values[key])
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="设备注册失败：唯一约束冲突") from exc
    db.refresh(obj)
    return obj


@router.post("/devices/{device_id}/heartbeat", response_model=DeviceHeartbeatOut)
def receive_heartbeat(
    device_id: int,
    payload: DeviceHeartbeatIn,
    db: Session = Depends(get_db),
):
    device = _device_or_404(db, device_id)
    _validate_mission(db, payload.mission_id, device_id)
    existing = _existing_heartbeat(db, device_id, payload.client_heartbeat_id)
    if existing is not None:
        return existing

    obj = DeviceHeartbeat(device_id=device_id, **payload.model_dump())
    db.add(obj)
    # 心跳中的状态是设备自报状态；平台不根据缺失的传感器值臆造状态。
    device.status = payload.status
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        # 并发重试下，幂等键可能已被另一请求写入；返回已存在记录。
        existing = _existing_heartbeat(db, device_id, payload.client_heartbeat_id)
        if existing is not None:
            return existing
        raise HTTPException(status_code=409, detail="心跳写入失败：唯一约束冲突") from exc
    db.refresh(obj)
    return obj


@router.get("/devices/{device_id}/heartbeats", response_model=list[DeviceHeartbeatOut])
def list_heartbeats(
    device_id: int,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    _device_or_404(db, device_id)
    return list(
        db.scalars(
            select(DeviceHeartbeat)
            .where(DeviceHeartbeat.device_id == device_id)
            .order_by(DeviceHeartbeat.observed_at.desc(), DeviceHeartbeat.id.desc())
            .limit(limit)
        ).all()
    )


def _create_event(
    db: Session,
    *,
    device_id: int | None,
    mission_id: int | None,
    payload: DeviceEventIn,
    is_fault_injected: bool = False,
    fault_type: str | None = None,
    fault_active: bool | None = None,
) -> DeviceEvent:
    if device_id is not None:
        _device_or_404(db, device_id)
    mission = _validate_mission(db, mission_id, device_id)
    if mission is not None and device_id is None:
        device_id = mission.device_id
    existing = _existing_event(db, device_id, payload.client_event_id)
    if existing is not None:
        return existing

    data = payload.model_dump(exclude={"device_id", "mission_id"})
    obj = DeviceEvent(
        device_id=device_id,
        mission_id=mission_id,
        is_fault_injected=is_fault_injected,
        fault_type=fault_type,
        fault_active=fault_active,
        **data,
    )
    db.add(obj)
    if device_id is not None and not is_fault_injected:
        device = _device_or_404(db, device_id)
        _apply_event_status(device, payload.event_type, payload.severity)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = _existing_event(db, device_id, payload.client_event_id)
        if existing is not None:
            return existing
        raise HTTPException(status_code=409, detail="事件写入失败：唯一约束冲突") from exc
    db.refresh(obj)
    return obj


@router.post("/devices/{device_id}/events", response_model=DeviceEventOut, status_code=201)
def receive_device_event(
    device_id: int,
    payload: DeviceEventIn,
    db: Session = Depends(get_db),
):
    _device_or_404(db, device_id)
    if payload.device_id is not None and payload.device_id != device_id:
        raise HTTPException(status_code=409, detail="事件中的设备与路径不匹配")
    return _create_event(
        db,
        device_id=device_id,
        mission_id=payload.mission_id,
        payload=payload,
    )


@router.get("/devices/{device_id}/events", response_model=list[DeviceEventOut])
def list_device_events(
    device_id: int,
    fault_injected: bool | None = Query(None),
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    _device_or_404(db, device_id)
    stmt = select(DeviceEvent).where(DeviceEvent.device_id == device_id)
    if fault_injected is not None:
        stmt = stmt.where(DeviceEvent.is_fault_injected.is_(fault_injected))
    return list(
        db.scalars(stmt.order_by(DeviceEvent.occurred_at.desc(), DeviceEvent.id.desc()).limit(limit)).all()
    )


@router.post("/devices/{device_id}/fault-injection", response_model=DeviceEventOut, status_code=201)
def inject_device_fault(
    device_id: int,
    payload: FaultInjectionIn,
    db: Session = Depends(get_db),
):
    device = _device_or_404(db, device_id)
    _validate_mission(db, payload.mission_id, device_id)
    existing = _existing_event(db, device_id, payload.client_event_id)
    if existing is not None:
        return existing

    event = DeviceEvent(
        device_id=device_id,
        mission_id=payload.mission_id,
        client_event_id=payload.client_event_id,
        event_type="fault_injected",
        severity=payload.severity,
        source="test",
        occurred_at=payload.occurred_at,
        is_fault_injected=True,
        fault_type=payload.fault_type,
        fault_active=payload.active,
        payload={**payload.payload, "fault_type": payload.fault_type, "active": payload.active},
        note=payload.note,
    )
    db.add(event)
    # 注入只改变平台可观察的测试状态，清除时恢复空闲；不伪造底盘动作。
    device.status = "maintenance" if payload.active else "idle"
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = _existing_event(db, device_id, payload.client_event_id)
        if existing is not None:
            return existing
        raise HTTPException(status_code=409, detail="故障注入失败：唯一约束冲突") from exc
    db.refresh(event)
    return event


@router.post("/missions/{mission_id}/events", response_model=DeviceEventOut, status_code=201)
def receive_mission_event(
    mission_id: int,
    payload: DeviceEventIn,
    db: Session = Depends(get_db),
):
    mission = _mission_or_404(db, mission_id)
    if payload.mission_id is not None and payload.mission_id != mission_id:
        raise HTTPException(status_code=409, detail="事件中的任务与路径不匹配")
    if mission.device_id is not None and payload.device_id is not None and mission.device_id != payload.device_id:
        raise HTTPException(status_code=409, detail="任务与设备不匹配")
    return _create_event(
        db,
        device_id=payload.device_id or mission.device_id,
        mission_id=mission_id,
        payload=payload,
    )


@router.get("/missions/{mission_id}/events", response_model=list[DeviceEventOut])
def list_mission_events(
    mission_id: int,
    limit: int = Query(100, ge=1, le=500),
    db: Session = Depends(get_db),
):
    _mission_or_404(db, mission_id)
    return list(
        db.scalars(
            select(DeviceEvent)
            .where(DeviceEvent.mission_id == mission_id)
            .order_by(DeviceEvent.occurred_at.desc(), DeviceEvent.id.desc())
            .limit(limit)
        ).all()
    )
