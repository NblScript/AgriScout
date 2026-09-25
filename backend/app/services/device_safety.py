"""设备安全锁存：维护态（maintenance）的进入与解除规则。

进入：真实安全事件（急停/看门狗/低电压/障碍，error 及以上）、故障注入生效、人工置为维护。
解除：
- 设备自报（心跳/注册）永远不能解除——否则一条默认心跳就会静默解除急停；
- 人工在设备管理中改状态可以解除，并留一条 ``status_override`` 事件（谁何时解除可审计）；
- 清除故障注入只解除「仅由注入造成」的锁：上次人工改状态之后若还有真实安全事件、
  其他仍生效的注入故障或人工置入维护，保持锁存。

事件按 id（到达顺序）判定先后，不依赖设备时钟。
"""
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Device, DeviceEvent

SAFETY_EVENT_TYPES = frozenset({
    "emergency_stop",
    "watchdog_timeout",
    "low_voltage",
    "obstacle",
    "fault_injected",
})
STATUS_OVERRIDE = "status_override"


def is_locking_event(event_type: str, severity: str) -> bool:
    """只对明确的安全事件进入维护态，不推断普通业务事件的硬件状态。"""
    return event_type in SAFETY_EVENT_TYPES and severity in {"error", "critical"}


def record_status_override(db: Session, device: Device, new_status: str, note: str | None = None) -> None:
    """人工改设备状态时留痕；状态未变不记。调用方负责提交。"""
    if new_status == device.status:
        return
    db.add(DeviceEvent(
        device_id=device.id,
        event_type=STATUS_OVERRIDE,
        severity="info",
        source="manual",
        occurred_at=datetime.now(timezone.utc),
        payload={"from": device.status, "to": new_status},
        note=note,
    ))


def lock_reasons(db: Session, device_id: int) -> list[str]:
    """当前仍成立的锁存原因；空列表表示锁只由已清除的注入故障造成，可以解除。

    调用前须 flush，保证本次刚写入的事件（如故障清除）参与判定。
    """
    last_override = db.scalar(
        select(DeviceEvent)
        .where(DeviceEvent.device_id == device_id, DeviceEvent.event_type == STATUS_OVERRIDE)
        .order_by(DeviceEvent.id.desc())
        .limit(1)
    )
    reasons: list[str] = []
    since_id = 0
    if last_override is not None:
        since_id = last_override.id
        if (last_override.payload or {}).get("to") == "maintenance":
            reasons.append(f"人工置入维护（事件 #{last_override.id}）")

    injected: dict[str, bool] = {}
    events = db.scalars(
        select(DeviceEvent)
        .where(DeviceEvent.device_id == device_id, DeviceEvent.id > since_id)
        .order_by(DeviceEvent.id)
    ).all()
    for event in events:
        if event.is_fault_injected:
            if event.fault_type:
                injected[event.fault_type] = bool(event.fault_active)
        elif is_locking_event(event.event_type, event.severity):
            reasons.append(f"{event.event_type}（事件 #{event.id}）")
    reasons += [f"注入故障 {fault} 未清除" for fault, active in injected.items() if active]
    return reasons


def release_after_fault_clear(db: Session, device: Device) -> list[str]:
    """清除一个注入故障后尝试解锁；返回仍成立的锁存原因（为空才会置回 idle）。"""
    db.flush()
    reasons = lock_reasons(db, device.id)
    if device.status == "maintenance" and not reasons:
        device.status = "idle"
    return reasons
