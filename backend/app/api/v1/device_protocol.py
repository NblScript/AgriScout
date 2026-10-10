"""采集端设备协议：注册、心跳、事件和故障注入。

故障注入只写入可回放的 ``DeviceEvent``，用于故障注入测试和状态机联调，
不把测试请求当成真实编码器、RTK、天气或急停结果。
"""
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select
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
from app.services.clock_check import heartbeat_warnings
from app.services.device_safety import is_locking_event, release_after_fault_clear

router = APIRouter(tags=["device-protocol"])


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


def _utc_naive(value: datetime) -> datetime:
    """统一成 UTC 无时区时间再比较（SQLite 读回的时间不带时区）。"""
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _apply_self_reported_status(device: Device, reported: str) -> None:
    """设备自报状态（心跳/注册）的更新规则。

    维护态是安全锁存（规则见 services/device_safety.py）：设备自报的 idle/active
    不能解除它，否则一条默认心跳就会静默解除急停。
    """
    if device.status == "maintenance" and reported != "maintenance":
        return
    device.status = reported


def _is_latest_heartbeat(db: Session, device_id: int, observed_at: datetime) -> bool:
    """乱序到达的旧心跳只留档，不覆盖设备当前状态。"""
    latest = db.scalar(
        select(func.max(DeviceHeartbeat.observed_at)).where(DeviceHeartbeat.device_id == device_id)
    )
    return latest is None or _utc_naive(observed_at) >= _utc_naive(latest)


def _apply_event_status(device: Device, event_type: str, severity: str) -> None:
    if is_locking_event(event_type, severity):
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
        for key in ("name", "type", "model", "notes"):
            if key in values:
                setattr(obj, key, values[key])
        if "status" in values:
            _apply_self_reported_status(obj, values["status"])
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

    is_latest = _is_latest_heartbeat(db, device_id, payload.observed_at)
    data = payload.model_dump()
    # 时钟检查（计划 0007 P0-2，D26）：只有车端自己填了 observed_at 才算时间差，没填的由平台补当前时间
    skew, warnings = heartbeat_warnings(
        observed_at=payload.observed_at if "observed_at" in payload.model_fields_set else None,
        clock=data["clock"], received_at=datetime.now(timezone.utc),
    )
    obj = DeviceHeartbeat(device_id=device_id, **data, clock_skew_s=skew, time_warnings=warnings or None)
    db.add(obj)
    # 心跳中的状态是设备自报状态；平台不根据缺失的传感器值臆造状态。
    if is_latest:
        _apply_self_reported_status(device, payload.status)
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
    # 注入只改变平台可观察的测试状态，不伪造底盘动作。清除时只解除「仅由注入造成」的锁：
    # 真实急停、其他仍生效的注入故障、人工置入维护都会保持锁存。
    if payload.active:
        device.status = "maintenance"
    else:
        release_after_fault_clear(db, device)
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
