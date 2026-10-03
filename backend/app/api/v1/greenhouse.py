"""棚内环境、每株状态、风险驱动巡检计划（计划 0015）。业务在 services/greenhouse_plans.py 与三个纯函数服务里。"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.timeutil import field_date, to_utc
from app.models import Device, Field
from app.schemas.greenhouse import (
    SENSOR_KEY_PATTERN,
    EnvSummaryOut,
    EnvUploadIn,
    EnvUploadOut,
    PatrolPlanIn,
    PatrolPlanOut,
    PlantStateOut,
)
from app.services import greenhouse_plans
from app.services.patrol_planner import DEFAULT_PARAMS

router = APIRouter(tags=["greenhouse"])
MAX_ENV_RANGE = timedelta(days=92)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _field_or_404(db: Session, field_id: int) -> Field:
    field = db.get(Field, field_id)
    if field is None:
        raise HTTPException(status_code=404, detail="地块不存在")
    return field


@router.post("/fields/{field_id}/env-readings", response_model=EnvUploadOut)
def upload_env_readings(field_id: int, payload: EnvUploadIn, db: Session = Depends(get_db)):
    """上报温湿度记录仪读数（每次最多 5000 条）。同一传感器同一时刻重复上报跳过；不带时区的时间按 UTC 解释。"""
    _field_or_404(db, field_id)
    device_id = None
    if payload.device is not None:
        device_id = db.scalar(select(Device.id).where(Device.code == payload.device))
        if device_id is None:
            raise HTTPException(status_code=404, detail="设备不存在")
    inserted, skipped = greenhouse_plans.insert_env_readings(
        db, field_id, payload.sensor_key, [r.model_dump() for r in payload.readings],
        device_id=device_id, source=payload.source,
    )
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="同一传感器有并发上报冲突，请重试（重复的时刻会自动跳过）") from None
    return EnvUploadOut(inserted=inserted, skipped=skipped)


@router.get("/fields/{field_id}/env", response_model=EnvSummaryOut)
def field_env(
    field_id: int,
    since: datetime | None = Query(None, description="默认 until 前 7 天"),
    until: datetime | None = Query(None, description="默认最新一条读数之后（没有读数时为当前时间）"),
    sensor_key: str | None = Query(None, pattern=SENSOR_KEY_PATTERN),
    db: Session = Depends(get_db),
):
    """小时聚合（缺测小时只标记）、逐日霜霉病指标、截至 until 的环境指数和清晨窗口。"""
    _field_or_404(db, field_id)
    if until is None:
        latest = greenhouse_plans.latest_reading_time(db, field_id)
        until = latest + timedelta(seconds=1) if latest is not None else _now()
    until = to_utc(until)
    since = to_utc(since) if since is not None else until - timedelta(days=7)
    if since >= until:
        raise HTTPException(status_code=422, detail="since 必须早于 until")
    if until - since > MAX_ENV_RANGE:
        raise HTTPException(status_code=422, detail="查询范围最长 92 天")
    days = max(1, round((until - since).total_seconds() / 86400))
    summary = greenhouse_plans.env_summary(db, field_id, until, history_days=days, sensor_key=sensor_key)
    hourly = [h for h in summary["hourly"] if h["hour"] >= since.replace(minute=0, second=0, microsecond=0)]
    daily_dates = {field_date(h["hour"]) for h in hourly}
    return EnvSummaryOut(
        field_id=field_id, since=since, until=until, sensors=summary["sensors"], hourly=hourly,
        daily=[d for d in summary["daily"] if d["field_date"] in daily_dates],
        index=summary["index"], morning_window=summary["morning_window"], params=summary["params"],
    )


@router.get("/fields/{field_id}/plant-states", response_model=list[PlantStateOut])
def field_plant_states(field_id: int, db: Session = Depends(get_db)):
    """在册各株的当前状态：人工确认优先，没有人工结论时用模型分占位（WP5 之前不是诊断）。"""
    _field_or_404(db, field_id)
    return [greenhouse_plans.state_row(ctx) for ctx in greenhouse_plans.unit_contexts(db, field_id, _now())]


@router.post("/fields/{field_id}/patrol-plans", response_model=PatrolPlanOut)
def create_patrol_plan(field_id: int, payload: PatrolPlanIn, db: Session = Depends(get_db)):
    """生成一天的巡检计划并写成任务；同株同类型的未完成任务复用，重复调用不会重复建任务。"""
    _field_or_404(db, field_id)
    now = _now()
    try:
        params = DEFAULT_PARAMS.with_overrides(payload.overrides)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return greenhouse_plans.generate_plan(
        db, field_id, plan_date=payload.plan_date or greenhouse_plans.today(now), now=now,
        created_by=payload.created_by, params=params,
    )


@router.get("/fields/{field_id}/patrol-plans/latest", response_model=PatrolPlanOut)
def latest_patrol_plan(field_id: int, db: Session = Depends(get_db)):
    _field_or_404(db, field_id)
    plan = greenhouse_plans.latest_plan(db, field_id)
    if plan is None:
        raise HTTPException(status_code=404, detail="该地块还没有生成过巡检计划")
    return plan
