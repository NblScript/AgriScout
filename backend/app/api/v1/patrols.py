"""Patrol 巡检任务查询 + 分析触发。"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy import func, select, update
from sqlalchemy.orm import Session, selectinload

from app.api.deps import patrol_or_404
from app.core.db import get_db, get_session_factory
from app.models import Analysis, CapturePoint
from app.models.patrol import Patrol
from app.schemas.analysis import PatrolAnalysisSummaryOut
from app.schemas.capture_point import PatrolDetailOut, PatrolOut
from app.schemas.common import Page
from app.services.analysis import Analyzer, get_analyzer
from app.services.analysis.runner import run_patrol_analysis
from app.services.storage import Storage, get_storage

router = APIRouter(prefix="/patrols", tags=["patrols"])

# 分析处于 running 但超过该时长无任何进展（进程崩溃/重启遗留），允许重新抢占
STALE_RUNNING_AFTER = timedelta(minutes=10)


def _utc_naive(value: datetime) -> datetime:
    if value.tzinfo is not None:
        value = value.astimezone(timezone.utc).replace(tzinfo=None)
    return value


def _running_is_stale(db: Session, patrol: Patrol) -> bool:
    """最后进展 = max(巡检更新时间, 最近一条逐点分析时间)；逐点提交保证正常运行时持续刷新。"""
    last_analysis = db.scalar(
        select(func.max(Analysis.analyzed_at)).where(Analysis.patrol_id == patrol.id)
    )
    marks = [m for m in (patrol.updated_at, last_analysis) if m is not None]
    if not marks:
        return True
    last = max(_utc_naive(m) for m in marks)
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    return now - last > STALE_RUNNING_AFTER


def _apply_filters(stmt, field_id: int | None, status: str | None, analysis_status: str | None):
    if field_id is not None:
        stmt = stmt.where(Patrol.field_id == field_id)
    if status is not None:
        stmt = stmt.where(Patrol.status == status)
    if analysis_status is not None:
        stmt = stmt.where(Patrol.analysis_status == analysis_status)
    return stmt


@router.get("", response_model=Page[PatrolOut])
def list_patrols(
    field_id: int | None = None,
    status: str | None = None,
    analysis_status: str | None = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    base = _apply_filters(select(Patrol), field_id, status, analysis_status)
    total = db.scalar(select(func.count()).select_from(base.subquery())) or 0
    # field_name/device_code 是触发懒加载的 property：不预载则每行 2 次查询（2N+1）
    rows = db.scalars(
        base.options(selectinload(Patrol.field), selectinload(Patrol.device))
        .order_by(Patrol.id.desc()).offset(skip).limit(limit)
    ).all()
    return Page(items=list(rows), total=total, skip=skip, limit=limit)


def _patrol_detail_or_404(db: Session, patrol_id: int) -> Patrol:
    """带关联预载的版本（PatrolDetailOut 需要 field/device/capture_points）。"""
    obj = db.scalars(
        select(Patrol)
        .options(
            selectinload(Patrol.field),
            selectinload(Patrol.device),
            selectinload(Patrol.capture_points),
        )
        .where(Patrol.id == patrol_id)
    ).first()
    if obj is None:
        raise HTTPException(status_code=404, detail="巡检任务不存在")
    return obj


@router.get("/{patrol_id}", response_model=PatrolDetailOut)
def get_patrol(patrol_id: int, db: Session = Depends(get_db)):
    return _patrol_detail_or_404(db, patrol_id)


@router.post("/{patrol_id}/analyze", status_code=202)
def reanalyze_patrol(
    patrol_id: int,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    analyzer: Analyzer = Depends(get_analyzer),
    storage: Storage = Depends(get_storage),
    session_factory=Depends(get_session_factory),
):
    """手动重分析（升级 analyzer 或数据修复后使用）。立即返回 202，后台执行。"""
    patrol = patrol_or_404(db, patrol_id)
    if patrol.analysis_status == "running":
        if not _running_is_stale(db, patrol):
            raise HTTPException(status_code=409, detail="该巡检正在分析中，请等待完成后再重试")
        # 超时无进展的 running 视为上次进程中断的遗留：释放锁后重新调度
        db.execute(
            update(Patrol)
            .where(Patrol.id == patrol_id, Patrol.analysis_status == "running")
            .values(analysis_status="error")
        )
        db.commit()
    background_tasks.add_task(
        run_patrol_analysis, patrol_id, analyzer, storage, session_factory,
    )
    return {"status": "scheduled", "patrol_id": patrol_id}


@router.get("/{patrol_id}/analysis-summary", response_model=PatrolAnalysisSummaryOut)
def analysis_summary(patrol_id: int, db: Session = Depends(get_db)):
    patrol = patrol_or_404(db, patrol_id)
    analyses = db.scalars(
        select(Analysis).where(Analysis.patrol_id == patrol_id)
    ).all()

    vigor_dist: dict[str, int] = {}
    stage_hist: dict[str, int] = {}
    ndvi_values: list[float] = []
    risk_values: list[float] = []
    stress_flagged = 0

    for a in analyses:
        if a.vigor_level is not None:
            key = str(a.vigor_level)
            vigor_dist[key] = vigor_dist.get(key, 0) + 1
        if a.ndvi is not None:
            ndvi_values.append(a.ndvi)
        if a.risk_score is not None:
            risk_values.append(a.risk_score)
        if a.disease_detections:
            stress_flagged += 1
        stage_name = (a.growth_stage or {}).get("name")
        if stage_name:
            stage_hist[str(stage_name)] = stage_hist.get(str(stage_name), 0) + 1

    # 多版本混存时取最近一次分析所用引擎（字符串 max 会按字典序误判 v10 < v9）
    latest = max(analyses, key=lambda a: (a.analyzed_at, a.id), default=None)
    avg_ndvi = round(sum(ndvi_values) / len(ndvi_values), 3) if ndvi_values else None
    avg_risk = round(sum(risk_values) / len(risk_values), 3) if risk_values else None

    return PatrolAnalysisSummaryOut(
        patrol_id=patrol.id,
        analysis_status=patrol.analysis_status,
        total_points=len(patrol.capture_points),
        analyzed_points=len(analyses),
        analyzer_version=latest.analyzer_version if latest else None,
        vigor_distribution=dict(sorted(vigor_dist.items())),
        avg_ndvi=avg_ndvi,
        avg_risk_score=avg_risk,
        stage_histogram=stage_hist,
        stress_flagged_points=stress_flagged,
    )
