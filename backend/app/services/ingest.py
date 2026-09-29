"""巡检包接入：解析协议 → 单事务落库。

红线（见 ARCHITECTURE.md「数据流」）：本模块只落库不做识别；
分析由 M3 的后台任务接手，Patrol.analysis_status 驱动进度。
"""
import logging

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
        planting = db.get(Planting, planting_id)
        if planting is None:
            raise ValueError(f"planting_id={planting_id} 不存在")
        # 种植批次决定生育期与作物专属规则：挂到别的地块的批次会让分析和建议整体错位
        if planting.field_id != field_id:
            raise ValueError(
                f"planting_id={planting_id} 属于地块 {planting.field_id}，与巡检地块 {field_id} 不一致"
            )
        return planting_id
    # 未显式指定 → 取该地块最新的生长期种植记录
    planting = db.scalars(
        select(Planting)
        .where(Planting.field_id == field_id, Planting.status == "active")
        .order_by(Planting.id.desc())
    ).first()
    return planting.id if planting else None


def _resolve_photo(payload: CapturePointPayload, storage: Storage) -> tuple[str | None, bool, bool]:
    """返回 (photo_url, 是否 base64 上传, 是否本次新建文件)。URL 引用直接透传。

    内容寻址去重：同图已在库中（可能被其他巡检引用）时“新建”为 False，回滚时不得删除。
    """
    photo = payload.photo
    if photo is None:
        return None, False, False
    if is_photo_url(photo):
        return photo, False, False
    data = decode_base64_photo(photo)  # 已在 schema 预校验，这里取字节
    # 按文件魔数判型：PNG(\x89PNG) / JPEG(\xff\xd8)，其余默认 jpg
    ext = ".png" if data[:4] == b"\x89PNG" else ".jpg"
    url, created = storage.save_tracked(data, suffix=ext)
    return url, True, created


def _cleanup_new_photos(db: Session, storage: Storage, urls: list[str]) -> None:
    """回滚后清理本次新建的照片；已被其他采样点引用的（并发上传同图）保留。"""
    logger = logging.getLogger(__name__)
    for url in urls:
        try:
            still_used = db.scalar(
                select(CapturePoint.id).where(CapturePoint.photo_url == url).limit(1)
            )
            if still_used is None:
                storage.delete(url)
        except Exception:  # noqa: BLE001 清理失败不影响主错误抛出
            logger.warning("orphan photo cleanup failed: %s", url)


def ingest_patrol_package(db: Session, package: PatrolPackageIn, storage: Storage) -> IngestResultOut:
    header = package.patrol

    field = db.get(Field, header.field_id)
    if field is None:
        raise ReferenceNotFound(f"地块不存在：field_id={header.field_id}")

    device = db.scalars(select(Device).where(Device.code == header.device)).first()
    if device is None:
        raise ReferenceNotFound(f"设备未登记：code={header.device}（先在设备管理中登记）")

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
    # 本次新建的照片文件 URL：落库失败时清理，避免孤儿文件（去重命中的共享照片不在此列）
    created_photo_urls: list[str] = []
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

    try:
        for cp in package.capture_points:
            photo_url, uploaded, created = _resolve_photo(cp, storage)
            if created and photo_url:
                created_photo_urls.append(photo_url)
            photos_saved += int(uploaded)
            photos_referenced += int(cp.photo is not None and not uploaded)
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
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        _cleanup_new_photos(db, storage, created_photo_urls)
        raise ValueError("巡检包落库失败：约束冲突（检查 seq 是否重复）") from exc
    except Exception:
        # 存储写盘等其他失败同样整包回滚，已新建的照片一并清理
        db.rollback()
        _cleanup_new_photos(db, storage, created_photo_urls)
        raise

    return IngestResultOut(
        patrol_id=patrol.id,
        capture_points=len(package.capture_points),
        photos_saved=photos_saved,
        photos_referenced=photos_referenced,
    )


class ReferenceNotFound(LookupError):
    """巡检包引用的地块/设备不存在（→404）。

    单独定义而不直接用 LookupError：IndexError/KeyError 也是 LookupError 子类，
    内部 bug 会被误映射成 404 并暴露 "list index out of range" 这类文案。
    """


class DuplicateError(Exception):
    """同地块+设备+开始时间的重复上传。"""

    def __init__(self, duplicate_id: int) -> None:
        super().__init__("重复上传")
        self.duplicate_id = duplicate_id
