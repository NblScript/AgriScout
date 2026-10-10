"""巡检包接入：解析协议 → 单事务落库。

红线（见 ARCHITECTURE.md「数据流」）：本模块只落库不做识别；
分析由 M3 的后台任务接手，Patrol.analysis_status 驱动进度。
"""
import hashlib
import json
import logging
from datetime import datetime, timezone

from sqlalchemy import func, select
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
from app.services.clock_check import patrol_warnings
from app.services.observation_units import UnitResolver
from app.services.storage import Storage, photo_suffix


# 包摘要定稿后协议头部新加的可选字段
LATER_HEADER_FIELDS = ("clock",)


def package_digest(package: PatrolPackageIn) -> str:
    """校验后包的规范 JSON 的 SHA-256：判定同一包号的重传是否内容一致（计划 0014）。

    协议后来加的可选字段（头部 ``clock``，计划 0007 P0-2）为空时不进摘要，升级前收下的包重传时摘要不变。
    """
    data = package.model_dump(mode="json")
    for name in LATER_HEADER_FIELDS:
        if data["patrol"].get(name) is None:
            data["patrol"].pop(name, None)
    canonical = json.dumps(data, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _replay_result(db: Session, device_id: int, client_package_id: str, digest: str) -> IngestResultOut | None:
    """同设备同包号已落库：内容一致 → duplicate 结果；内容不同 → PackageConflict；没有 → None。"""
    existing = db.scalar(select(Patrol).where(
        Patrol.device_id == device_id, Patrol.client_package_id == client_package_id,
    ))
    if existing is None:
        return None
    if existing.package_sha256 != digest:
        raise PackageConflict(existing.id)
    points = db.scalar(select(func.count()).where(CapturePoint.patrol_id == existing.id)) or 0
    return IngestResultOut(
        patrol_id=existing.id, capture_points=points, photos_saved=0, photos_referenced=0, duplicate=True,
        warnings=[w["message"] for w in existing.time_warnings or []],
    )


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
    url, created = storage.save_tracked(data, suffix=photo_suffix(data))
    return url, True, created


def _check_media_refs(package: PatrolPackageIn, storage: Storage) -> None:
    """``/media/`` 开头的照片引用必须是平台上已有的照片（计划 0016-B）；外部 http(s) URL 不校验。

    rover 分步上传先经 ``POST /media`` 传照片、再提交只含 URL 的包；引用缺失多半是照片没传成功，
    整包拒绝（422），让采集端把包留在队列里重传，而不是落一批取不到图的点。
    """
    missing = sorted({
        cp.photo for cp in package.capture_points
        if cp.photo and cp.photo.startswith("/media/") and not storage.exists(cp.photo)
    })
    if missing:
        shown = "、".join(missing[:3]) + (f" 等 {len(missing)} 个" if len(missing) > 3 else "")
        raise ValueError(f"照片引用在平台上不存在：{shown}（先用 POST /api/v1/media 上传）")


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


def ingest_patrol_package(
    db: Session, package: PatrolPackageIn, storage: Storage, *, received_at: datetime | None = None,
) -> IngestResultOut:
    header = package.patrol
    received_at = received_at or datetime.now(timezone.utc)

    field = db.get(Field, header.field_id)
    if field is None:
        raise ReferenceNotFound(f"地块不存在：field_id={header.field_id}")

    device = db.scalars(select(Device).where(Device.code == header.device)).first()
    if device is None:
        raise ReferenceNotFound(f"设备未登记：code={header.device}（先在设备管理中登记）")

    planting_id = _resolve_planting(db, header.field_id, header.planting_id)

    # 带包号：先按 (设备, 包号) 判幂等，再走原有的三元组判重
    digest = package_digest(package) if header.client_package_id else None
    if header.client_package_id:
        replay = _replay_result(db, device.id, header.client_package_id, digest)
        if replay is not None:
            return replay

    duplicate = db.scalars(
        select(Patrol).where(
            Patrol.field_id == header.field_id,
            Patrol.device_id == device.id,
            Patrol.started_at == header.started_at,
        )
    ).first()
    if duplicate is not None:
        raise DuplicateError(duplicate_id=duplicate.id)
    _check_media_refs(package, storage)

    photos_saved = 0
    photos_referenced = 0
    # 本次新建的照片文件 URL：落库失败时清理，避免孤儿文件（去重命中的共享照片不在此列）
    created_photo_urls: list[str] = []
    clock = header.clock.model_dump(mode="json") if header.clock is not None else None
    # 时间告警只提示不拒收（计划 0007 P0-2，D26）：时间错了也是现场数据，入库后由人判断
    warnings = patrol_warnings(
        started_at=header.started_at, ended_at=header.ended_at,
        captured=[cp.captured_at for cp in package.capture_points], clock=clock, received_at=received_at,
    )
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
        schema_version=package.schema_version,
        client_package_id=header.client_package_id,
        package_sha256=digest,
        clock=clock,
        time_warnings=warnings or None,
    )
    units = UnitResolver(db, field.id)

    try:
        db.add(patrol)
        db.flush()  # 取 patrol.id 供子表外键使用；尚未提交，失败即整体回滚
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
                observation_key=cp.observation_key,
                # 找不到株档案就自动建档（created_from=ingest），不丢数据，留给人工核对
                observation_unit_id=units.resolve(cp.observation_key).id if cp.observation_key else None,
                route_chainage_m=cp.route_chainage_m,
                distance_source=cp.distance_source,
                position_source=cp.position_source,
                view_meta=cp.view.model_dump(mode="json") if cp.view is not None else None,
            )
            if cp.weather is not None:
                point.weather = WeatherSample(patrol_id=patrol.id, **cp.weather.model_dump())
            db.add(point)
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        _cleanup_new_photos(db, storage, created_photo_urls)
        if header.client_package_id:
            # 并发重传撞上 (设备, 包号) 唯一约束：对方已落库，按幂等规则重新判定
            replay = _replay_result(db, device.id, header.client_package_id, digest)
            if replay is not None:
                return replay
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
        warnings=[w["message"] for w in warnings],
    )


class ReferenceNotFound(LookupError):
    """巡检包引用的地块/设备不存在（→404）。

    单独定义而不直接用 LookupError：IndexError/KeyError 也是 LookupError 子类，
    内部 bug 会被误映射成 404 并暴露 "list index out of range" 这类文案。
    """


class PackageConflict(Exception):
    """同设备同包号、内容不同的上传（→409，带已有 patrol_id）。"""

    def __init__(self, existing_id: int) -> None:
        super().__init__("包号冲突")
        self.existing_id = existing_id


class DuplicateError(Exception):
    """同地块+设备+开始时间的重复上传。"""

    def __init__(self, duplicate_id: int) -> None:
        super().__init__("重复上传")
        self.duplicate_id = duplicate_id
