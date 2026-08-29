"""巡检包接入：解析协议 → 单事务落库。

红线（见 docs/05 任务流水线）：本模块只落库不做识别；
分析由 M3 的后台任务接手，Patrol.analysis_status 驱动进度。
"""
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import CapturePoint, Device, Field, Patrol, Planting, WeatherSample
from app.schemas.patrol import (
    CapturePointPayload,
    IngestResultOut,
    PatrolPackageIn,
    decode_base64_photo,
    is_photo_url,
)
from app.services.storage import Storage


def _resolve_planting(db: Session, field_id: int, planting_id: int | None) -> int | None:
    if planting_id is not None:
        if db.get(Planting, planting_id) is None:
            raise ValueError(f"planting_id={planting_id} 不存在")
        return planting_id
    # 未显式指定 → 取该地块最新的生长期种植记录
    planting = db.scalars(
        select(Planting)
        .where(Planting.field_id == field_id, Planting.status == "active")
        .order_by(Planting.id.desc())
    ).first()
    return planting.id if planting else None


def _resolve_photo(payload: CapturePointPayload, storage: Storage) -> tuple[str | None, bool]:
    """返回 (photo_url, 是否本次落盘)。URL 引用直接透传。"""
    photo = payload.photo
    if photo is None:
        return None, False
    if is_photo_url(photo):
        return photo, False
    data = decode_base64_photo(photo)  # 已在 schema 预校验，这里取字节
    # 按文件魔数判型：PNG(\x89PNG) / JPEG(\xff\xd8)，其余默认 jpg
    ext = ".png" if data[:4] == b"\x89PNG" else ".jpg"
    return storage.save(data, suffix=ext), True


def ingest_patrol_package(db: Session, package: PatrolPackageIn, storage: Storage) -> IngestResultOut:
    header = package.patrol

    field = db.get(Field, header.field_id)
    if field is None:
        raise LookupError(f"地块不存在：field_id={header.field_id}")

    device = db.scalars(select(Device).where(Device.code == header.device)).first()
    if device is None:
        raise LookupError(f"设备未登记：code={header.device}（先在设备管理中登记）")

    planting_id = _resolve_planting(db, header.field_id, header.planting_id)

    duplicate = db.scalars(
        select(Patrol).where(
            Patrol.field_id == header.field_id,
            Patrol.device_id == device.id,
            Patrol.started_at == header.started_at,
        )
    ).first()
    if duplicate is not None:
        raise DuplicateError(duplicate_id=duplicate.id)

    photos_saved = 0
    photos_referenced = 0
    # 本次新落盘的照片 URL：落库失败时逐一清理，避免孤儿文件
    saved_photo_urls: list[str] = []
    patrol = Patrol(
        field_id=field.id,
        planting_id=planting_id,
        device_id=device.id,
        started_at=header.started_at,
        ended_at=header.ended_at,
        track=header.to_linestring(),
        status="received",
        analysis_status="pending",
        notes=header.notes,
    )
    db.add(patrol)
    db.flush()  # 取 patrol.id 供子表外键使用；尚未提交，失败即整体回滚

    for cp in package.capture_points:
        photo_url, saved = _resolve_photo(cp, storage)
        if saved and photo_url:
            saved_photo_urls.append(photo_url)
        photos_saved += int(saved)
        photos_referenced += int(cp.photo is not None and not saved)
        point = CapturePoint(
            patrol_id=patrol.id,
            seq=cp.seq,
            distance_m=cp.distance_m,
            lng=cp.lng,
            lat=cp.lat,
            captured_at=cp.captured_at,
            photo_url=photo_url,
        )
        if cp.weather is not None:
            point.weather = WeatherSample(patrol_id=patrol.id, **cp.weather.model_dump())
        db.add(point)

    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        for url in saved_photo_urls:  # 单事务回滚了，落盘的照片须一并清理
            try:
                storage.delete(url)
            except Exception:  # noqa: BLE001 清理失败不影响主错误抛出
                logging.getLogger(__name__).warning("orphan photo cleanup failed: %s", url)
        raise ValueError("巡检包落库失败：约束冲突（检查 seq 是否重复）") from exc

    return IngestResultOut(
        patrol_id=patrol.id,
        capture_points=len(package.capture_points),
        photos_saved=photos_saved,
        photos_referenced=photos_referenced,
    )


class DuplicateError(Exception):
    """同地块+设备+开始时间的重复上传。"""

    def __init__(self, duplicate_id: int) -> None:
        super().__init__("重复上传")
        self.duplicate_id = duplicate_id
