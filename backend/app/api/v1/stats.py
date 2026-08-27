"""Stats 平台聚合统计：一次请求喂饱指挥大屏（避免前端并发拉十几个列表）。"""
from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import Analysis, Advice, Annotation, CapturePoint, Crop, Device, Field, Patrol, Planting
from app.schemas.stats import RecentPatrolStat, StatsOverview

router = APIRouter(tags=["stats"])

RECENT_PATROL_COUNT = 5


def _count(db: Session, stmt) -> int:
    return db.scalar(select(func.count()).select_from(stmt.subquery())) or 0


@router.get("/stats/overview", response_model=StatsOverview)
def stats_overview(db: Session = Depends(get_db)):
    analyzed_points = db.scalar(select(func.count()).select_from(Analysis)) or 0
    advice_status = dict(
        db.execute(select(Advice.status, func.count()).group_by(Advice.status)).all()
    )

    recent = db.scalars(
        select(Patrol).order_by(Patrol.started_at.desc(), Patrol.id.desc()).limit(RECENT_PATROL_COUNT)
    ).all()
    ids = [p.id for p in recent]

    # 一次把近几次巡检的分析行拉回内存聚合（规模 ≤ 5 包，比多条 group-by 更省 round-trip）
    analysis_rows = db.execute(
        select(Analysis.patrol_id, Analysis.vigor_level, Analysis.ndvi, Analysis.risk_score,
               Analysis.disease_detections)
        .where(Analysis.patrol_id.in_(ids))
    ).all() if ids else []

    per_patrol: dict[int, dict] = {
        p.id: {"vigor": {}, "ndvi": [], "risk": [], "stress": 0, "analyzed": 0} for p in recent
    }
    for pid, vigor, ndvi, risk, diseases in analysis_rows:
        agg = per_patrol[pid]
        agg["analyzed"] += 1
        if vigor is not None:
            key = str(vigor)
            agg["vigor"][key] = agg["vigor"].get(key, 0) + 1
        if ndvi is not None:
            agg["ndvi"].append(ndvi)
        if risk is not None:
            agg["risk"].append(risk)
        if diseases:
            agg["stress"] += 1

    point_counts = dict(
        db.execute(
            select(CapturePoint.patrol_id, func.count())
            .where(CapturePoint.patrol_id.in_(ids))
            .group_by(CapturePoint.patrol_id)
        ).all()
    ) if ids else {}

    field_names = dict(db.execute(select(Field.id, Field.name)).all()) if recent else {}

    recent_stats = [
        RecentPatrolStat(
            patrol_id=p.id,
            field_name=field_names.get(p.field_id),
            started_at=p.started_at,
            point_count=point_counts.get(p.id, 0),
            analyzed_points=per_patrol[p.id]["analyzed"],
            avg_ndvi=round(sum(per_patrol[p.id]["ndvi"]) / len(per_patrol[p.id]["ndvi"]), 3)
            if per_patrol[p.id]["ndvi"] else None,
            avg_risk_score=round(sum(per_patrol[p.id]["risk"]) / len(per_patrol[p.id]["risk"]), 3)
            if per_patrol[p.id]["risk"] else None,
            vigor_distribution=per_patrol[p.id]["vigor"],
            stress_points=per_patrol[p.id]["stress"],
        )
        for p in recent
    ]

    return StatsOverview(
        fields=db.scalar(select(func.count()).select_from(Field)) or 0,
        crops=db.scalar(select(func.count()).select_from(Crop)) or 0,
        plantings=db.scalar(select(func.count()).select_from(Planting)) or 0,
        devices=db.scalar(select(func.count()).select_from(Device)) or 0,
        patrols=db.scalar(select(func.count()).select_from(Patrol)) or 0,
        capture_points=db.scalar(select(func.count()).select_from(CapturePoint)) or 0,
        analyzed_points=analyzed_points,
        annotations=db.scalar(select(func.count()).select_from(Annotation)) or 0,
        advices_total=sum(advice_status.values()),
        advices_suggested=advice_status.get("suggested", 0),
        advices_accepted=advice_status.get("accepted", 0),
        advices_rejected=advice_status.get("rejected", 0),
        recent_patrols=recent_stats,
    )
