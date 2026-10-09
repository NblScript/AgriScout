"""申报书软件闭环 API：风险、复巡、随访、数据集和模型评估。"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.timeutil import field_date, to_utc
from app.models import Analysis, CapturePoint, DatasetVersion, Device, Field, FollowUp, ModelEvaluation, Patrol, RevisitTask, RiskPrediction
from app.services.dataset_governance import (
    SplitSpec,
    approve_model_evaluation as governance_approve_model_evaluation,
    freeze_dataset_version,
    recompute_metrics,
)
from app.services.evaluation_metrics import LabeledPrediction, WindowPrediction, evaluate_predictions, event_lead_times
from app.services.evidence_feedback import InvalidTransitionError, check_completeness, transition_status
from app.services.risk_inputs import build_region_series, region_evidence
from app.services.risk_model import RegionRisk, is_lr_version, load_model, predict_regions
from app.services import revisit_planning
from app.services.risk_prediction import predict_region_risk
from app.schemas.software_loop import (
    DatasetFreezeIn, DatasetVersionCreate, DatasetVersionOut, FollowUpIn, FollowUpOut,
    ModelApproveIn, ModelEvaluationCreate, ModelEvaluationOut, RevisitTaskCreate,
    RevisitTaskOut, RevisitTaskUpdate, RiskGenerateIn, RiskPredictionCreate,
    RiskPredictionOut, TaskGenerateIn,
)

router = APIRouter(tags=["software-loop"])
CN_TZ = timezone(timedelta(hours=8))
FOLLOW_UP_STATUSES = {"pending", "confirmed_positive", "confirmed_negative", "insufficient", "intervened", "unknown"}
TASK_TRANSITIONS = {
    "queued": {"assigned", "cancelled"}, "assigned": {"running", "cancelled", "queued"},
    "running": {"completed", "cancelled"}, "completed": set(), "cancelled": set(),
}


def _now() -> datetime:
    return datetime.now(CN_TZ)


def _prediction_or_404(db: Session, prediction_id: int) -> RiskPrediction:
    obj = db.get(RiskPrediction, prediction_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="风险预测不存在")
    return obj


def _task_or_404(db: Session, task_id: int) -> RevisitTask:
    obj = db.get(RevisitTask, task_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="复巡任务不存在")
    return obj


def _level(probability: float) -> str:
    return "high" if probability >= 0.7 else "medium" if probability >= 0.4 else "low"


@router.post("/risk-predictions", response_model=RiskPredictionOut, status_code=201)
def create_risk_prediction(payload: RiskPredictionCreate, db: Session = Depends(get_db)):
    # 统一换算 UTC：一端带时区一端不带时直接相减会 TypeError（500）
    forecast_start, forecast_end = to_utc(payload.forecast_start), to_utc(payload.forecast_end)
    if forecast_end <= forecast_start:
        raise HTTPException(status_code=422, detail="预测结束时间必须晚于开始时间")
    expected_seconds = payload.forecast_hours * 3600
    actual_seconds = (forecast_end - forecast_start).total_seconds()
    if abs(actual_seconds - expected_seconds) > 1:
        raise HTTPException(status_code=422, detail="预测时间窗必须与 forecast_hours 一致")
    patrol = db.get(Patrol, payload.patrol_id)
    if patrol is None:
        raise HTTPException(status_code=404, detail="巡检不存在")
    if payload.capture_point_id is not None:
        point = db.get(CapturePoint, payload.capture_point_id)
        if point is None or point.patrol_id != patrol.id:
            raise HTTPException(status_code=422, detail="采样点不属于该巡检")
    existing_stmt = select(RiskPrediction).where(
        RiskPrediction.patrol_id == payload.patrol_id,
        RiskPrediction.target_event == payload.target_event,
        RiskPrediction.forecast_start == payload.forecast_start,
        RiskPrediction.forecast_hours == payload.forecast_hours,
        RiskPrediction.model_version == payload.model_version,
    )
    if payload.capture_point_id is None:
        existing_stmt = existing_stmt.where(RiskPrediction.capture_point_id.is_(None))
    else:
        existing_stmt = existing_stmt.where(RiskPrediction.capture_point_id == payload.capture_point_id)
    existing = db.scalar(existing_stmt)
    if existing is not None:
        return existing
    data = payload.model_dump()
    data["level"] = _level(payload.probability)
    obj = RiskPrediction(**data)
    db.add(obj)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(existing_stmt)
        if existing is None:
            raise
        return existing
    db.refresh(obj)
    return obj


@router.get("/risk-predictions", response_model=list[RiskPredictionOut])
def list_risk_predictions(
    patrol_id: int | None = Query(None, gt=0), status: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db),
):
    stmt = select(RiskPrediction).order_by(RiskPrediction.created_at.desc(), RiskPrediction.id.desc())
    if patrol_id is not None:
        stmt = stmt.where(RiskPrediction.patrol_id == patrol_id)
    if status is not None:
        stmt = stmt.where(RiskPrediction.status == status)
    return list(db.scalars(stmt.limit(limit)).all())


@router.get("/patrols/{patrol_id}/risk-predictions", response_model=list[RiskPredictionOut])
def list_patrol_predictions(patrol_id: int, db: Session = Depends(get_db)):
    if db.get(Patrol, patrol_id) is None:
        raise HTTPException(status_code=404, detail="巡检不存在")
    return list(db.scalars(select(RiskPrediction).where(RiskPrediction.patrol_id == patrol_id).order_by(RiskPrediction.forecast_start, RiskPrediction.id)).all())


def _model_approval(db: Session, model_version: str) -> dict:
    """模型版本的审批状态：同版本号的模型评估是否已通过发布闸门（D11/0009：不强制，但必须可追溯）。"""
    approved = db.scalar(
        select(ModelEvaluation)
        .where(ModelEvaluation.model_version == model_version, ModelEvaluation.status == "approved")
        .order_by(ModelEvaluation.approved_at.desc())
    )
    if approved is None:
        return {"status": "unapproved"}
    return {"status": "approved", "evaluation_id": approved.id, "approved_by": approved.approved_by,
            "approved_at": approved.approved_at.isoformat() if approved.approved_at else None}


def _heuristic_region_risks(inputs, payload: RiskGenerateIn) -> dict[str, RegionRisk]:
    """启发式基线（risk-heuristic-*）：区域时间序列 → predict_region_risk。"""
    results = {}
    for key, series in inputs.series.items():
        baseline = predict_region_risk(
            observations=series.observations, horizon_hours=payload.forecast_hours,
            as_of=series.current["captured_at"], model_version=payload.model_version,
        )
        # 证据不足时保留 unknown：缺失/低质量观测不得静默当作低风险（0005 决策）
        results[key] = RegionRisk(
            probability=baseline.probability, level=baseline.level, trend=baseline.trend,
            confidence=baseline.confidence,
            evidence={"prediction_evidence": list(baseline.evidence),
                      "feature_values": dict(baseline.feature_values),
                      "recheck_window_hours": list(baseline.recheck_window_hours),
                      "limitations": ["启发式区域基线（区域关联 grid-v0），待病种数据训练与独立评估"]},
        )
    return results


@router.post("/patrols/{patrol_id}/risk-predictions/generate", response_model=list[RiskPredictionOut])
def generate_patrol_predictions(patrol_id: int, payload: RiskGenerateIn, db: Session = Depends(get_db)):
    """把逐点分析转为有窗口、有依据的风险记录。

    输入是区域级时间序列（本次 + 回看窗口内的历史巡检，见 services/risk_inputs.py）；
    预测仍按采样点落库（复巡任务需要具体点位），同一区域同一趟巡检的点共享区域级结果。
    model_version 以 risk-lr- 开头时使用训练好的逻辑回归模型文件（计划 0009），否则用启发式基线。
    """
    patrol = db.get(Patrol, patrol_id)
    if patrol is None:
        raise HTTPException(status_code=404, detail="巡检不存在")
    rows = list(db.scalars(select(Analysis).where(Analysis.patrol_id == patrol_id).order_by(Analysis.capture_point_id)).all())
    if not rows:
        raise HTTPException(status_code=422, detail="该巡检尚无逐点分析结果")
    lr_model = None
    if is_lr_version(payload.model_version):
        try:
            lr_model = load_model(payload.model_version)
            lr_model.check_request(
                target_event=payload.target_event, forecast_hours=payload.forecast_hours,
                cell_m=payload.region_cell_m, history_days=payload.history_days,
            )
        except (FileNotFoundError, ValueError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    try:
        inputs = build_region_series(
            db, patrol, cell_m=payload.region_cell_m, history_days=payload.history_days,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    if lr_model is not None:
        region_risks = predict_regions(lr_model, inputs, patrol.id, _model_approval(db, payload.model_version))
    else:
        region_risks = _heuristic_region_risks(inputs, payload)
    points = {p.id: p for p in patrol.capture_points}
    output: list[RiskPrediction] = []
    for analysis in rows:
        point = points.get(analysis.capture_point_id)
        key = inputs.point_key.get(analysis.capture_point_id)
        if point is None or key is None:
            continue
        risk = region_risks[key]
        obj = RiskPrediction(
            patrol_id=patrol_id, capture_point_id=point.id,
            observation_key=key, target_event=payload.target_event,
            forecast_hours=payload.forecast_hours, forecast_start=point.captured_at,
            forecast_end=point.captured_at + timedelta(hours=payload.forecast_hours),
            probability=risk.probability, level=risk.level, trend=risk.trend,
            confidence=risk.confidence, model_version=payload.model_version,
            evidence={"source": "region-analysis", "analyzer_version": analysis.analyzer_version,
                      "risk_score": analysis.risk_score, "features": analysis.detail or {},
                      "region": region_evidence(inputs.series[key], inputs.grid),
                      **risk.evidence},
        )
        existing = db.scalar(select(RiskPrediction).where(
            RiskPrediction.patrol_id == patrol_id,
            RiskPrediction.capture_point_id == point.id,
            RiskPrediction.target_event == payload.target_event,
            RiskPrediction.forecast_start == point.captured_at,
            RiskPrediction.forecast_hours == payload.forecast_hours,
            RiskPrediction.model_version == payload.model_version,
        ))
        if existing is not None:
            output.append(existing)
            continue
        db.add(obj)
        output.append(obj)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        output = list(db.scalars(select(RiskPrediction).where(
            RiskPrediction.patrol_id == patrol_id,
            RiskPrediction.target_event == payload.target_event,
            RiskPrediction.forecast_hours == payload.forecast_hours,
            RiskPrediction.model_version == payload.model_version,
        ).order_by(RiskPrediction.capture_point_id)).all())
    for obj in output:
        db.refresh(obj)
    return output


@router.get("/risk-predictions/metrics")
def risk_prediction_metrics(
    target_event: str = Query(min_length=1),
    model_version: str = Query(min_length=1),
    field_id: int | None = Query(None, gt=0),
    fp_per_unit: float = Query(2.0, ge=0, description="每个地块·日允许的误报条数"),
    lead_threshold: float | None = Query(
        None, ge=0, le=1,
        description="计算提前量时视为「已预警」的概率阈值；缺省取固定误报负担下的阈值（与 recall_at_fp 同一阈值）",
    ),
    calibrate: bool = Query(False, description="按时间前后拆分做等渗校准，比较校准前后 Brier"),
    db: Session = Depends(get_db),
):
    """根据随访结论评估一个模型版本在一个目标事件上的表现（申报书 9.2）。

    同一模型版本、同一目标事件才能放在一起评估，因此两者必填。标签口径见 services/evaluation_metrics.py：
    处置过的按删失处理，证据不足/未知/没有随访的不进分母，只计数。
    """
    stmt = (
        select(RiskPrediction, FollowUp, Patrol.field_id)
        .join(Patrol, RiskPrediction.patrol_id == Patrol.id)
        .outerjoin(FollowUp, FollowUp.risk_prediction_id == RiskPrediction.id)
        .where(RiskPrediction.target_event == target_event, RiskPrediction.model_version == model_version)
    )
    if field_id is not None:
        stmt = stmt.where(Patrol.field_id == field_id)
    rows = db.execute(stmt).all()
    records, events, windows = [], [], []
    for prediction, follow, pred_field_id in rows:
        start = to_utc(prediction.forecast_start)
        status = follow.status if follow is not None else None
        records.append(LabeledPrediction(
            probability=prediction.probability, status=status,
            unit=(pred_field_id, field_date(start)), order_key=(start, prediction.id),
        ))
        windows.append(WindowPrediction(
            prediction.observation_key, start, to_utc(prediction.forecast_end), prediction.probability,
        ))
        if status == "confirmed_positive" and follow.event_at is not None:
            events.append((prediction.observation_key, to_utc(follow.event_at)))
    report = evaluate_predictions(records, fp_per_unit=fp_per_unit, calibrate=calibrate)
    # 申报书 9.2：提前量要在「相同误报负担」下比较——固定概率阈值对不同模型不公平
    # （分数整体偏高的模型在同一阈值下几乎全田报警，提前量看起来反而更好）
    threshold = lead_threshold if lead_threshold is not None else report["recall_at_fp"]["threshold"]
    if threshold is None:
        report["lead_time"] = {"threshold": None, "events": len(set(events)),
                               "note": "没有可评估的阳性或误报预算内无可用阈值，无法计算提前量"}
    else:
        report["lead_time"] = {
            **event_lead_times(sorted(set(events)), windows, threshold),
            "threshold_source": "指定" if lead_threshold is not None else f"每地块·日误报 ≤ {fp_per_unit:g}",
        }
    report["scope"] = {
        "target_event": target_event, "model_version": model_version, "field_id": field_id,
        "predictions": len(records), "unit": "地块·日（田间时区）",
    }
    return report


def _check_follow_up_timing(prediction: RiskPrediction, payload: FollowUpIn) -> None:
    """随访结论必须对得上预测窗口，否则会变成错误的训练/评估标签（申报书 8.2）。

    - 确认阴性：窗口结束前「还没发病」不等于阴性，必须等窗口走完；
    - 确认阳性：给了事件时间就必须落在窗口内——窗口前已有的症状不是该窗口的新发事件，
      窗口后才出现的也不能算这次预测命中；
    - event_confirmed 与状态不得自相矛盾。
    """
    start, end = to_utc(prediction.forecast_start), to_utc(prediction.forecast_end)
    if payload.status == "confirmed_negative":
        if datetime.now(timezone.utc) < end:
            raise HTTPException(
                status_code=422,
                detail=f"预测窗口 {end.isoformat()} 才结束，窗口内未发病不能提前确认阴性（可先记 pending/insufficient）",
            )
        if payload.event_confirmed:
            raise HTTPException(status_code=422, detail="确认阴性与 event_confirmed=true 矛盾")
    if payload.status == "confirmed_positive" and payload.event_confirmed is False:
        raise HTTPException(status_code=422, detail="确认阳性与 event_confirmed=false 矛盾")
    if payload.event_at is not None:
        event_at = to_utc(payload.event_at)
        if event_at < start:
            raise HTTPException(status_code=422, detail="事件时间早于预测窗口开始，不是该窗口内的新发事件")
        if payload.status == "confirmed_positive" and event_at > end:
            raise HTTPException(status_code=422, detail="事件时间晚于预测窗口结束，不能作为该预测的阳性")


@router.post("/risk-predictions/{prediction_id}/follow-up", response_model=FollowUpOut)
def upsert_follow_up(prediction_id: int, payload: FollowUpIn, db: Session = Depends(get_db)):
    prediction = _prediction_or_404(db, prediction_id)
    if payload.status not in FOLLOW_UP_STATUSES:
        raise HTTPException(status_code=422, detail="不支持的随访状态")
    follow = db.scalar(select(FollowUp).where(FollowUp.risk_prediction_id == prediction_id))
    if follow is None:
        follow = FollowUp(risk_prediction_id=prediction_id, status="pending")
        db.add(follow)
        current_status = None
    else:
        current_status = follow.status
    if payload.status != "pending":
        evidence = payload.evidence or {}
        if not any(evidence.get(key) for key in (
            "reference", "photo_url", "photo_urls", "annotation_id", "annotation_ids", "dataset_row_id",
        )):
            raise HTTPException(status_code=422, detail="随访必须提供照片、标注或其他可定位的证据引用")
        completeness = check_completeness(
            {
                "alert_id": prediction.id,
                "observation_region": prediction.observation_key,
                "prediction_window": {
                    "start": prediction.forecast_start,
                    "end": prediction.forecast_end,
                },
                "model_version": prediction.model_version,
                "evidence": payload.evidence,
                "status": payload.status,
                "human_conclusion": payload.note or payload.event_confirmed,
                "follow_up": payload.evidence,
                "intervention": payload.intervention_at,
            }
        )
        if not completeness.complete:
            raise HTTPException(
                status_code=422,
                detail=f"随访证据不完整：{', '.join(completeness.issues)}",
            )
    if current_status not in {"confirmed_positive", "confirmed_negative", "intervened"}:
        _check_follow_up_timing(prediction, payload)
    if current_status in {"confirmed_positive", "confirmed_negative", "intervened"}:
        current_values = {key: getattr(follow, key) for key in payload.model_fields}
        if payload.status != current_status or any(
            current_values[key] != value for key, value in payload.model_dump().items()
        ):
            raise HTTPException(status_code=409, detail="终态随访不可修改，请新建后续观察记录")
        return follow
    try:
        if current_status is None and payload.status != "pending":
            transition_status(None, "pending")
            transition_status("pending", payload.status)
        else:
            transition_status(current_status, payload.status)
    except InvalidTransitionError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    for key, value in payload.model_dump().items():
        setattr(follow, key, value)
    follow.reviewed_at = _now()
    prediction.status = "closed" if payload.status in {"confirmed_positive", "confirmed_negative", "intervened"} else "open"
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(select(FollowUp).where(FollowUp.risk_prediction_id == prediction_id))
        if existing is not None:
            raise HTTPException(status_code=409, detail="该预测刚被提交随访，请刷新后重试") from exc
        raise
    db.refresh(follow)
    return follow


@router.get("/risk-predictions/{prediction_id}/follow-up", response_model=FollowUpOut | None)
def get_follow_up(prediction_id: int, db: Session = Depends(get_db)):
    _prediction_or_404(db, prediction_id)
    return db.scalar(select(FollowUp).where(FollowUp.risk_prediction_id == prediction_id))


@router.post("/revisit-tasks", response_model=RevisitTaskOut, status_code=201)
def create_revisit_task(payload: RevisitTaskCreate, db: Session = Depends(get_db)):
    if db.get(Field, payload.field_id) is None:
        raise HTTPException(status_code=404, detail="地块不存在")
    if payload.patrol_id is not None and db.get(Patrol, payload.patrol_id) is None:
        raise HTTPException(status_code=404, detail="巡检不存在")
    if payload.patrol_id is not None and db.get(Patrol, payload.patrol_id).field_id != payload.field_id:
        raise HTTPException(status_code=422, detail="任务地块与巡检不一致")
    if payload.capture_point_id is not None and db.get(CapturePoint, payload.capture_point_id) is None:
        raise HTTPException(status_code=404, detail="采样点不存在")
    if payload.capture_point_id is not None:
        point = db.get(CapturePoint, payload.capture_point_id)
        if payload.patrol_id is not None and point.patrol_id != payload.patrol_id:
            raise HTTPException(status_code=422, detail="任务采样点与巡检不一致")
        point_patrol = db.get(Patrol, point.patrol_id)
        if point_patrol is None or point_patrol.field_id != payload.field_id:
            raise HTTPException(status_code=422, detail="任务采样点与地块不一致")
    if payload.risk_prediction_id is not None and db.get(RiskPrediction, payload.risk_prediction_id) is None:
        raise HTTPException(status_code=404, detail="风险预测不存在")
    if payload.risk_prediction_id is not None:
        prediction = db.get(RiskPrediction, payload.risk_prediction_id)
        if prediction.patrol_id != payload.patrol_id and payload.patrol_id is not None:
            raise HTTPException(status_code=422, detail="任务风险预测与巡检不一致")
        prediction_patrol = db.get(Patrol, prediction.patrol_id)
        if prediction_patrol is None or prediction_patrol.field_id != payload.field_id:
            raise HTTPException(status_code=422, detail="任务风险预测与地块不一致")
        if payload.capture_point_id is not None and prediction.capture_point_id != payload.capture_point_id:
            raise HTTPException(status_code=422, detail="任务风险预测与采样点不一致")
    if payload.device_id is not None and db.get(Device, payload.device_id) is None:
        raise HTTPException(status_code=404, detail="设备不存在")
    obj = RevisitTask(**payload.model_dump())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/revisit-tasks", response_model=list[RevisitTaskOut])
def list_revisit_tasks(
    field_id: int | None = Query(None, gt=0), status: str | None = Query(None), task_type: str | None = Query(None),
    limit: int = Query(100, ge=1, le=500), db: Session = Depends(get_db),
):
    stmt = select(RevisitTask).order_by(RevisitTask.priority.desc(), RevisitTask.created_at.desc())
    if field_id is not None:
        stmt = stmt.where(RevisitTask.field_id == field_id)
    if status is not None:
        stmt = stmt.where(RevisitTask.status == status)
    if task_type is not None:
        stmt = stmt.where(RevisitTask.task_type == task_type)
    return list(db.scalars(stmt.limit(limit)).all())


@router.patch("/revisit-tasks/{task_id}", response_model=RevisitTaskOut)
def update_revisit_task(task_id: int, payload: RevisitTaskUpdate, db: Session = Depends(get_db)):
    obj = _task_or_404(db, task_id)
    values = payload.model_dump(exclude_unset=True)
    next_status = values.get("status")
    if obj.status in {"completed", "cancelled"} and any(key != "status" for key in values):
        raise HTTPException(status_code=409, detail="已结束的复巡任务不可修改")
    if next_status is not None and next_status != obj.status and next_status not in TASK_TRANSITIONS.get(obj.status, set()):
        raise HTTPException(status_code=422, detail=f"任务状态不能从 {obj.status} 转为 {next_status}")
    if "device_id" in values and values["device_id"] is not None and db.get(Device, values["device_id"]) is None:
        raise HTTPException(status_code=404, detail="设备不存在")
    for key, value in values.items():
        setattr(obj, key, value)
    if next_status == "completed" and obj.completed_at is None:
        obj.completed_at = _now()
    db.commit()
    db.refresh(obj)
    return obj


@router.post("/revisit-tasks/generate", response_model=list[RevisitTaskOut])
def generate_revisit_tasks(payload: TaskGenerateIn, db: Session = Depends(get_db)):
    """按区域去重后用联合策略排序生成复巡任务（逻辑见 services/revisit_planning.py，与离线重放共用实现）。"""
    if db.get(Field, payload.field_id) is None:
        raise HTTPException(status_code=404, detail="地块不存在")
    if payload.patrol_id is not None:
        patrol = db.get(Patrol, payload.patrol_id)
        if patrol is None:
            raise HTTPException(status_code=404, detail="巡检不存在")
        if patrol.field_id != payload.field_id:
            raise HTTPException(status_code=422, detail="任务地块与巡检不一致")
    return revisit_planning.generate_revisit_tasks(
        db, field_id=payload.field_id, patrol_id=payload.patrol_id, limit=payload.limit,
        created_by=payload.created_by, interval_days=payload.patrol_interval_days,
    )


@router.get("/devices/{device_id}/tasks/next", response_model=RevisitTaskOut | None)
def next_device_task(device_id: int, db: Session = Depends(get_db)):
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status_code=404, detail="设备不存在")
    if device.status == "maintenance":
        # 安全锁存中的设备不领取新任务（急停/低电压/故障注入未解除）
        return None
    obj = db.scalar(select(RevisitTask).where(
        RevisitTask.status == "queued",
        (RevisitTask.device_id == device_id) | RevisitTask.device_id.is_(None),
    ).order_by(RevisitTask.priority.desc(), RevisitTask.created_at))
    if obj is not None:
        claim = db.execute(update(RevisitTask).where(
            RevisitTask.id == obj.id, RevisitTask.status == "queued",
            (RevisitTask.device_id == device_id) | RevisitTask.device_id.is_(None),
        ).values(device_id=device_id, status="assigned"))
        if claim.rowcount != 1:
            db.rollback()
            return None
        db.commit()
        db.refresh(obj)
    return obj


@router.post("/datasets/versions", response_model=DatasetVersionOut, status_code=201)
def create_dataset_version(payload: DatasetVersionCreate, db: Session = Depends(get_db)):
    obj = DatasetVersion(**payload.model_dump())
    db.add(obj)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail="数据集名称和版本已存在") from exc
    db.refresh(obj)
    return obj


@router.get("/datasets/versions", response_model=list[DatasetVersionOut])
def list_dataset_versions(db: Session = Depends(get_db)):
    return list(db.scalars(select(DatasetVersion).order_by(DatasetVersion.created_at.desc())).all())


@router.post("/datasets/versions/{dataset_id}/freeze", response_model=DatasetVersionOut)
def freeze_dataset(dataset_id: int, payload: DatasetFreezeIn, db: Session = Depends(get_db)):
    obj = db.get(DatasetVersion, dataset_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="数据集版本不存在")
    try:
        split = SplitSpec(**payload.split.model_dump()) if payload.split else None
        freeze_dataset_version(db, obj, split=split, now=_now())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/datasets/versions/{dataset_id}/snapshot")
def get_dataset_snapshot(dataset_id: int, db: Session = Depends(get_db)):
    obj = db.get(DatasetVersion, dataset_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="数据集版本不存在")
    if obj.status != "frozen" or not obj.snapshot_ndjson:
        raise HTTPException(status_code=409, detail="数据集尚未冻结或没有快照")
    return Response(
        content=obj.snapshot_ndjson,
        media_type="application/x-ndjson",
        headers={"Content-Disposition": f'attachment; filename="{obj.name}-{obj.version}.jsonl"'},
    )


@router.post("/model-evaluations", response_model=ModelEvaluationOut, status_code=201)
def create_model_evaluation(payload: ModelEvaluationCreate, db: Session = Depends(get_db)):
    dataset = db.get(DatasetVersion, payload.dataset_version_id) if payload.dataset_version_id else None
    if payload.dataset_version_id and dataset is None:
        raise HTTPException(status_code=404, detail="数据集版本不存在")
    obj = ModelEvaluation(**payload.model_dump(exclude={"predictions", "threshold"}))
    if payload.predictions is not None:
        # 逐条预测当场对照冻结快照核对并重算指标（D24），对不上直接拒收
        if dataset is None:
            raise HTTPException(status_code=422, detail="提交逐条预测时必须绑定数据集")
        items = [item.model_dump() for item in payload.predictions]
        try:
            obj.platform_metrics = recompute_metrics(
                dataset, split=payload.split.lower(), predictions=items, threshold=payload.threshold,
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        obj.predictions = items
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj


@router.get("/model-evaluations", response_model=list[ModelEvaluationOut])
def list_model_evaluations(status: str | None = Query(None), db: Session = Depends(get_db)):
    stmt = select(ModelEvaluation).order_by(ModelEvaluation.evaluated_at.desc())
    if status:
        stmt = stmt.where(ModelEvaluation.status == status)
    return list(db.scalars(stmt).all())


@router.post("/model-evaluations/{evaluation_id}/approve", response_model=ModelEvaluationOut)
def approve_model_evaluation(evaluation_id: int, payload: ModelApproveIn, db: Session = Depends(get_db)):
    obj = db.get(ModelEvaluation, evaluation_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="模型评估不存在")
    if obj.status != "candidate":
        raise HTTPException(status_code=422, detail="该评估已决策")
    try:
        governance_approve_model_evaluation(db, obj, approved_by=payload.approved_by, now=_now())
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    db.refresh(obj)
    return obj
