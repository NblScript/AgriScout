"""建议线 L2 工具箱：诊断 Agent 的只读查询函数（全部 SELECT，零写入）。

查询统一走 ORM filter_by(kwargs)——关键字即绑定参数，无字符串拼 SQL。
工具入参经显式映射分发（safe_dispatch），不做 **kwargs 动态解包。
"""
from typing import Any

from sqlalchemy.orm import Session

from app.models import (
    Advice,
    Analysis,
    Annotation,
    CapturePoint,
    Crop,
    Device,
    Field,
    Patrol,
    PatrolReport,
    Planting,
)


def tool_get_field_overview(db: Session) -> dict:
    fields = db.query(Field).all()
    plantings = db.query(Planting).filter_by(status="active").all()
    devices = db.query(Device).all()
    return {
        "fields": [{"id": f.id, "name": f.name, "area_ha": f.area_ha, "soil_type": f.soil_type} for f in fields],
        "active_plantings": [
            {"id": p.id, "field_id": p.field_id, "field_name": p.field_name,
             "crop_name": p.crop_name, "sowing_date": str(p.sowing_date), "status": p.status}
            for p in plantings
        ],
        "devices": [{"id": d.id, "code": d.code, "name": d.name, "type": d.type, "status": d.status} for d in devices],
    }


def tool_get_patrol_detail(db: Session, patrol_id: int) -> dict:
    patrol = db.get(Patrol, patrol_id)
    if patrol is None:
        return {"error": f"巡检 {patrol_id} 不存在"}
    analyses = db.query(Analysis).filter_by(patrol_id=patrol_id).all()
    vigor: dict[str, int] = {}
    ndvi: list[float] = []
    risk: list[float] = []
    stress = 0
    stages: dict[str, int] = {}
    for a in analyses:
        if a.vigor_level is not None:
            vigor[str(a.vigor_level)] = vigor.get(str(a.vigor_level), 0) + 1
        if a.ndvi is not None:
            ndvi.append(a.ndvi)
        if a.risk_score is not None:
            risk.append(a.risk_score)
        if a.disease_detections:
            stress += 1
        stage = (a.growth_stage or {}).get("name")
        if stage:
            stages[stage] = stages.get(stage, 0) + 1
    report = db.query(PatrolReport).filter_by(patrol_id=patrol_id).one_or_none()
    return {
        "patrol_id": patrol.id,
        "field_name": patrol.field_name,
        "device_code": patrol.device_code,
        "started_at": str(patrol.started_at),
        "analysis_status": patrol.analysis_status,
        "point_count": len(analyses),
        "stage_distribution": stages,
        "vigor_distribution": vigor,
        "avg_ndvi_proxy": round(sum(ndvi) / len(ndvi), 3) if ndvi else None,
        "avg_risk_score": round(sum(risk) / len(risk), 3) if risk else None,
        "stress_points": stress,
        "llm_report_exists": report is not None,
        "llm_report_head": (report.content[:300] if report else None),
    }


def tool_get_point_samples(
    db: Session, patrol_id: int, vigor_level: int | None = None,
    risk_min: float | None = None, limit: int = 10,
) -> dict:
    points = db.query(CapturePoint).filter_by(patrol_id=patrol_id).all()
    rows = []
    for p in points:
        a = p.analysis
        if a is None:
            continue
        if vigor_level is not None and a.vigor_level != vigor_level:
            continue
        if risk_min is not None and (a.risk_score or 0) < risk_min:
            continue
        rows.append({
            "seq": p.seq, "distance_m": p.distance_m,
            "vigor_level": a.vigor_level, "ndvi": a.ndvi, "risk_score": a.risk_score,
            "stage": (a.growth_stage or {}).get("name"),
            "stress_detected": bool(a.disease_detections),
            "soil_moisture": p.weather.soil_moisture_pct if p.weather else None,
        })
    rows.sort(key=lambda r: -(r["risk_score"] or 0))
    return {"matched": len(rows), "samples": rows[:limit]}


def tool_get_advices(db: Session, patrol_id: int, status: str | None = None, limit: int = 15) -> dict:
    query = db.query(Advice).filter_by(patrol_id=patrol_id)
    if status is not None:
        query = query.filter(Advice.status == status)
    total = query.count()
    items = query.order_by(Advice.created_at.desc()).limit(limit).all()
    return {
        "total": total,
        "items": [{
            "rule_key": a.rule_snapshot.get("rule_key"),
            "tier": a.rule_snapshot.get("tier"),
            "priority": a.priority,
            "status": a.status,
            "content": a.content[:200],
            "source": a.rule_snapshot.get("source"),
        } for a in items],
    }


def tool_get_annotations(db: Session, patrol_id: int | None = None, limit: int = 30) -> dict:
    query = db.query(Annotation)
    if patrol_id is not None:
        query = query.filter(Annotation.patrol_id == patrol_id)
    total = query.count()
    items = query.order_by(Annotation.updated_at.desc()).limit(limit).all()
    return {
        "total": total,
        "items": [{
            "patrol_id": a.patrol_id, "capture_point_id": a.capture_point_id,
            "label": a.label, "annotator": a.annotator_name,
            "note": (a.note or "")[:100], "at": str(a.updated_at),
        } for a in items],
    }


def tool_get_platform_stats(db: Session) -> dict:
    def _count(model) -> int:
        return db.query(model).count()

    from sqlalchemy import func

    advice_rows = (
        db.query(Advice.status, func.count())
        .group_by(Advice.status)
        .all()
    )
    latest = (
        db.query(Patrol)
        .order_by(Patrol.started_at.desc(), Patrol.id.desc())
        .limit(3).all()
    )
    return {
        "fields": _count(Field), "crops": _count(Crop), "devices": _count(Device),
        "patrols": _count(Patrol), "capture_points": _count(CapturePoint),
        "analyses": _count(Analysis), "annotations": _count(Annotation),
        "advice_status": {k: v for k, v in advice_rows},
        "recent_patrols": [{"id": p.id, "field": p.field_name, "at": str(p.started_at), "status": p.analysis_status} for p in latest],
    }


def safe_dispatch(db: Session, fn, arguments: dict[str, Any]) -> dict:
    """工具分发：白名单函数 + 显式参数提取与类型校验，不做动态解包。

    类型校验用 typing.get_args 正确处理 Optional[int] 等联合注解；
    不匹配的参数丢弃（回落到函数默认值），无法注入非预期 kwargs。
    """
    import inspect
    import typing

    allowed_types = (int, float, str, bool)  # isinstance 要求 tuple 而非 set
    args: dict[str, Any] = {}
    for key, value in arguments.items():
        if isinstance(value, allowed_types) or value is None:
            args[key] = value

    sig = inspect.signature(fn)
    kwargs: dict[str, Any] = {}
    for name, param in sig.parameters.items():
        if name == "db":
            continue
        annotation = param.annotation
        # Optional[int] 等联合注解 → 取非 None 的成员类型集合
        union_args = typing.get_args(annotation)
        member_types = {
            a for a in union_args
            if a is not type(None) and isinstance(a, type)
        } if union_args else (
            {annotation} if isinstance(annotation, type) else set()
        )
        if name in args:
            v = args[name]
            if v is None or any(isinstance(v, t) for t in member_types):
                kwargs[name] = v
        elif param.default is not inspect.Parameter.empty:
            kwargs[name] = param.default
    return fn(db, **kwargs)
