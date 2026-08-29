"""Annotation 人工标注：复核落库、巡检维度进度、NDJSON 数据集导出。"""
import json
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.api.deps import paged, patrol_or_404
from app.core.db import get_db
from app.models import Analysis, Annotation, CapturePoint, Patrol
from app.schemas.annotation import (
    AnnotationCreate,
    AnnotationOut,
    AnnotationUpdate,
    PatrolAnnotationSummary,
)
from app.schemas.common import Page

router = APIRouter(tags=["annotations"])


def _get_point_or_404(db: Session, point_id: int) -> CapturePoint:
    point = db.get(CapturePoint, point_id)
    if point is None:
        raise HTTPException(status_code=404, detail="采样点不存在")
    return point




def _get_annotation_or_404(db: Session, annotation_id: int) -> Annotation:
    ann = db.get(Annotation, annotation_id)
    if ann is None:
        raise HTTPException(status_code=404, detail="标注不存在")
    return ann


@router.post("/capture-points/{point_id}/annotations", response_model=AnnotationOut, status_code=201)
def create_annotation(point_id: int, payload: AnnotationCreate, response: Response, db: Session = Depends(get_db)):
    """提交复核结论：同点同标签幂等 upsert（updated_at 即最近复核时间）。"""
    point = _get_point_or_404(db, point_id)
    ann = db.scalar(
        select(Annotation).where(
            Annotation.capture_point_id == point_id,
            Annotation.label == payload.label,
        )
    )
    if ann is None:
        # label 即查询键，更新分支无需回写；仅创建分支需要赋值
        ann = Annotation(
            capture_point_id=point.id, patrol_id=point.patrol_id, label=payload.label,
        )
        db.add(ann)
        created = True
    else:
        created = False
    ann.annotator_name = payload.annotator_name
    ann.note = payload.note
    try:
        db.commit()
    except IntegrityError as exc:
        # 并发窗口：两个请求同时为同点同标签创建（查询时都未见对方）
        db.rollback()
        raise HTTPException(status_code=409, detail="该采样点刚被他人提交过同标签复核，请刷新后重试") from exc
    db.refresh(ann)
    if not created:
        response.status_code = 200
    return ann


@router.get("/capture-points/{point_id}/annotations", response_model=list[AnnotationOut])
def list_point_annotations(point_id: int, db: Session = Depends(get_db)):
    """单个采样点的全部复核记录（一点可有多类标签）。"""
    _get_point_or_404(db, point_id)
    rows = db.scalars(
        select(Annotation)
        .where(Annotation.capture_point_id == point_id)
        .order_by(Annotation.created_at, Annotation.id)
    ).all()
    return list(rows)


@router.get("/patrols/{patrol_id}/annotations/summary", response_model=PatrolAnnotationSummary)
def patrol_annotation_summary(patrol_id: int, db: Session = Depends(get_db)):
    """回放页进度徽标：总点数 / 已复核点数（去重）/ 标注条数。"""
    patrol_or_404(db, patrol_id)
    points_total = db.scalar(
        select(func.count()).select_from(CapturePoint).where(CapturePoint.patrol_id == patrol_id)
    ) or 0
    annotated_points = db.scalar(
        select(func.count(func.distinct(Annotation.capture_point_id)))
        .where(Annotation.patrol_id == patrol_id)
    ) or 0
    total = db.scalar(
        select(func.count()).select_from(Annotation).where(Annotation.patrol_id == patrol_id)
    ) or 0
    return {
        "patrol_id": patrol_id,
        "points_total": points_total,
        "annotated_points": annotated_points,
        "annotations_total": total,
    }


@router.get("/patrols/{patrol_id}/annotations", response_model=Page[AnnotationOut])
def list_patrol_annotations(
    patrol_id: int,
    label: str | None = Query(None),
    capture_point_id: int | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    patrol_or_404(db, patrol_id)
    stmt = select(Annotation).where(Annotation.patrol_id == patrol_id)
    if label is not None:
        stmt = stmt.where(Annotation.label == label)
    if capture_point_id is not None:
        stmt = stmt.where(Annotation.capture_point_id == capture_point_id)

    return paged(
        db, stmt, skip, limit,
        order_by=[Annotation.updated_at.desc(), Annotation.id.desc()],
    )


@router.patch("/annotations/{annotation_id}", response_model=AnnotationOut)
def update_annotation(annotation_id: int, payload: AnnotationUpdate, db: Session = Depends(get_db)):
    """修正复核结论（改标签/备注/标注人）；改撞已有 (点, 标签) 组合则 409。"""
    ann = _get_annotation_or_404(db, annotation_id)
    updates = payload.model_dump(exclude_unset=True)
    new_label = updates.get("label")
    if new_label and new_label != ann.label:
        clash = db.scalar(
            select(Annotation).where(
                Annotation.capture_point_id == ann.capture_point_id,
                Annotation.label == new_label,
            )
        )
        if clash is not None:
            raise HTTPException(status_code=409, detail="该采样点已存在同类标签，请直接修改原标注")
    for key, value in updates.items():
        setattr(ann, key, value)
    db.commit()
    db.refresh(ann)
    return ann


@router.delete("/annotations/{annotation_id}", status_code=204)
def delete_annotation(annotation_id: int, db: Session = Depends(get_db)):
    """误标撤回：删的是标注记录，不动照片与分析结果。"""
    ann = _get_annotation_or_404(db, annotation_id)
    db.delete(ann)
    db.commit()


@router.get("/annotations/export")
def export_dataset(
    patrol_id: int | None = Query(None),
    db: Session = Depends(get_db),
):
    """导出 NDJSON 训练集：每行 = 一条人工标注 + 对应照片与分析结论快照。

    供 YOLOv8n 微调（识别线 L1）直接消费；bbox 字段为画框功能预留，当前恒为 null。
    """
    if patrol_id is not None:
        patrol_or_404(db, patrol_id)
    stmt = (
        select(Annotation, CapturePoint, Analysis)
        .join(CapturePoint, Annotation.capture_point_id == CapturePoint.id)
        .outerjoin(Analysis, Analysis.capture_point_id == CapturePoint.id)
        .order_by(Annotation.patrol_id, CapturePoint.seq, Annotation.id)
    )
    if patrol_id is not None:
        stmt = stmt.where(Annotation.patrol_id == patrol_id)

    lines = []
    for ann, point, analysis in db.execute(stmt):

        def _iso(value: datetime | None) -> str | None:
            return value.isoformat() if value else None

        row = {
            "label": ann.label,
            "bbox": ann.bbox,
            "note": ann.note,
            "annotator_name": ann.annotator_name,
            "reviewed_at": _iso(ann.updated_at),
            "photo_url": point.photo_url,
            "point": {
                "seq": point.seq,
                "distance_m": point.distance_m,
                "lng": point.lng,
                "lat": point.lat,
                "captured_at": _iso(point.captured_at),
            },
            # 机器预测随行导出：训练前可对比人机分歧，优先标分歧样本
            "analysis": {
                "analyzer_version": analysis.analyzer_version,
                "growth_stage": analysis.growth_stage,
                "vigor_level": analysis.vigor_level,
                "ndvi": analysis.ndvi,
                "disease_detections": analysis.disease_detections,
                "risk_score": analysis.risk_score,
            } if analysis else None,
        }
        lines.append(json.dumps(row, ensure_ascii=False))

    name = f"agriscout-annotations-patrol-{patrol_id}.jsonl" if patrol_id else "agriscout-annotations-all.jsonl"
    body = "\n".join(lines) + ("\n" if lines else "")
    return Response(
        content=body,
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{name}"'},
    )
