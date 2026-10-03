"""株档案与单株时间线（计划 0014）：按株建档、批量建档、按株号串起每天的照片、复核与预测。"""
from collections import defaultdict
from datetime import timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app.core.db import get_db
from app.core.timeutil import field_date, to_utc
from app.models import Annotation, CapturePoint, Field, ObservationUnit, RiskPrediction
from app.schemas.observation_unit import (
    BulkCreateIn,
    BulkCreateOut,
    ObservationUnitCreate,
    ObservationUnitOut,
    ObservationUnitUpdate,
    TimelineAnalysis,
    TimelineAnnotation,
    TimelineDay,
    TimelinePhoto,
    TimelinePrediction,
    UnitSource,
    UnitStatus,
    UnitTimelineOut,
)
from app.services.observation_units import BulkRow, bulk_create_units, new_unit

router = APIRouter(tags=["observation-units"])


def _field_or_404(db: Session, field_id: int) -> Field:
    field = db.get(Field, field_id)
    if field is None:
        raise HTTPException(status_code=404, detail="地块不存在")
    return field


def _unit_or_404(db: Session, unit_id: int) -> ObservationUnit:
    unit = db.get(ObservationUnit, unit_id)
    if unit is None:
        raise HTTPException(status_code=404, detail="株档案不存在")
    return unit


@router.get("/fields/{field_id}/observation-units", response_model=list[ObservationUnitOut])
def list_units(
    field_id: int,
    row_no: int | None = Query(None, ge=1),
    status: UnitStatus | None = None,
    created_from: UnitSource | None = Query(None, description="ingest = 上传时自动建档、待人工核对"),
    db: Session = Depends(get_db),
):
    _field_or_404(db, field_id)
    stmt = select(ObservationUnit).where(ObservationUnit.field_id == field_id)
    if row_no is not None:
        stmt = stmt.where(ObservationUnit.row_no == row_no)
    if status is not None:
        stmt = stmt.where(ObservationUnit.status == status)
    if created_from is not None:
        stmt = stmt.where(ObservationUnit.created_from == created_from)
    # 推荐格式按 (垄, 株) 排；自定义键（垄号为空）排在后面按键名
    stmt = stmt.order_by(ObservationUnit.row_no.is_(None), ObservationUnit.row_no,
                         ObservationUnit.position_no, ObservationUnit.key)
    return list(db.scalars(stmt).all())


@router.post("/fields/{field_id}/observation-units", response_model=ObservationUnitOut, status_code=201)
def create_unit(field_id: int, payload: ObservationUnitCreate, db: Session = Depends(get_db)):
    _field_or_404(db, field_id)
    unit = new_unit(field_id, payload.key, created_from="manual",
                    chainage_m=payload.chainage_m, tag_code=payload.tag_code, note=payload.note)
    db.add(unit)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="该地块已有相同株号或标签的档案") from None
    db.refresh(unit)
    return unit


@router.post("/fields/{field_id}/observation-units/bulk", response_model=BulkCreateOut)
def bulk_create(field_id: int, payload: BulkCreateIn, db: Session = Depends(get_db)):
    """按推荐格式 R{垄号}-P{株序号} 批量建档；已有的株号跳过，可重复提交。"""
    _field_or_404(db, field_id)
    created, skipped = bulk_create_units(db, field_id, [BulkRow(**row.model_dump()) for row in payload.rows])
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="批量建档冲突（可能有并发建档），请重试") from None
    return BulkCreateOut(created=created, skipped=skipped)


@router.patch("/observation-units/{unit_id}", response_model=ObservationUnitOut)
def update_unit(unit_id: int, payload: ObservationUnitUpdate, db: Session = Depends(get_db)):
    unit = _unit_or_404(db, unit_id)
    for key, value in payload.model_dump(exclude_unset=True).items():
        setattr(unit, key, value)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="该地块已有相同标签的档案") from None
    db.refresh(unit)
    return unit


@router.get("/observation-units/{unit_id}/timeline", response_model=UnitTimelineOut)
def unit_timeline(
    unit_id: int,
    days: int = Query(30, ge=1, le=366, description="回看天数，从这株最近一次拍摄往前算"),
    db: Session = Depends(get_db),
):
    """单株时间线：按田间日期聚合这株的照片（含视角、补拍次数、质量）、人工复核和风险预测。"""
    unit = _unit_or_404(db, unit_id)
    points = list(db.scalars(
        select(CapturePoint)
        .options(selectinload(CapturePoint.analysis))
        .where(CapturePoint.observation_unit_id == unit.id)
        .order_by(CapturePoint.captured_at, CapturePoint.id)
    ).all())
    if points:
        # 窗口锚定在最近一次拍摄，而不是当前时间：历史数据和模拟季同样能看
        since = to_utc(points[-1].captured_at) - timedelta(days=days)
        points = [p for p in points if to_utc(p.captured_at) > since]
    point_ids = [p.id for p in points]
    date_of = {p.id: field_date(p.captured_at) for p in points}

    by_day: dict = defaultdict(lambda: {"photos": [], "annotations": [], "predictions": []})
    for point in points:
        analysis = point.analysis
        by_day[date_of[point.id]]["photos"].append(TimelinePhoto(
            capture_point_id=point.id, patrol_id=point.patrol_id, captured_at=point.captured_at,
            photo_url=point.photo_url, view=point.view_meta,
            analysis=TimelineAnalysis(
                risk_score=analysis.risk_score, disease_detections=analysis.disease_detections,
                analyzer_version=analysis.analyzer_version,
                image_quality=(analysis.detail or {}).get("image_quality"),
            ) if analysis is not None else None,
        ))
    if point_ids:
        for ann in db.scalars(select(Annotation).where(Annotation.capture_point_id.in_(point_ids))
                              .order_by(Annotation.id)):
            by_day[date_of[ann.capture_point_id]]["annotations"].append(TimelineAnnotation(
                id=ann.id, capture_point_id=ann.capture_point_id, label=ann.label,
                annotator_name=ann.annotator_name, note=ann.note, updated_at=ann.updated_at,
            ))
        predictions = db.scalars(
            select(RiskPrediction).options(selectinload(RiskPrediction.follow_up))
            .where(RiskPrediction.capture_point_id.in_(point_ids)).order_by(RiskPrediction.id)
        )
        for pred in predictions:
            by_day[date_of[pred.capture_point_id]]["predictions"].append(TimelinePrediction(
                id=pred.id, capture_point_id=pred.capture_point_id, target_event=pred.target_event,
                model_version=pred.model_version, probability=pred.probability, level=pred.level,
                trend=pred.trend, status=pred.status,
                follow_up_status=pred.follow_up.status if pred.follow_up is not None else None,
            ))
    return UnitTimelineOut(
        unit=ObservationUnitOut.model_validate(unit),
        days=[TimelineDay(field_date=day, **content) for day, content in sorted(by_day.items())],
    )
