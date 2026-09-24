"""申报书软件闭环 API：风险、复巡、随访、数据集和模型评估。"""
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query, Response
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import Analysis, CapturePoint, DatasetVersion, Device, Field, FollowUp, ModelEvaluation, Patrol, RevisitTask, RiskPrediction
from app.services.active_learning import ActiveLearningCandidate, SelectionConstraints, select_active_learning_tasks
from app.services.dataset_governance import (
    approve_model_evaluation as governance_approve_model_evaluation,
    freeze_dataset_version,
)
from app.services.evidence_feedback import InvalidTransitionError, check_completeness, transition_status
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
    if payload.forecast_end <= payload.forecast_start:
        raise HTTPException(status_code=422, detail="预测结束时间必须晚于开始时间")
    expected_seconds = payload.forecast_hours * 3600
    actual_seconds = (payload.forecast_end - payload.forecast_start).total_seconds()
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


@router.post("/patrols/{patrol_id}/risk-predictions/generate", response_model=list[RiskPredictionOut])
def generate_patrol_predictions(patrol_id: int, payload: RiskGenerateIn, db: Session = Depends(get_db)):
    """将逐点分析转为有窗口、有依据的风险记录；模型版本可替换为训练模型。"""
    patrol = db.get(Patrol, patrol_id)
    if patrol is None:
        raise HTTPException(status_code=404, detail="巡检不存在")
    rows = list(db.scalars(select(Analysis).where(Analysis.patrol_id == patrol_id).order_by(Analysis.capture_point_id)).all())
    if not rows:
        raise HTTPException(status_code=422, detail="该巡检尚无逐点分析结果")
    points = {p.id: p for p in patrol.capture_points}
    output: list[RiskPrediction] = []
    for analysis in rows:
        point = points.get(analysis.capture_point_id)
        if point is None:
            continue
        detail = analysis.detail or {}
        weather = point.weather
        observation = {
            "captured_at": point.captured_at,
            "risk_score": analysis.risk_score,
            "vigor_level": analysis.vigor_level,
            "disease_detections": analysis.disease_detections,
            "features": detail,
            "quality": detail.get("quality", {}),
            "environment": {
                key: getattr(weather, key)
                for key in ("temp_c", "humidity_pct", "light_lux", "wind_mps", "rain_mm", "soil_moisture_pct")
                if weather is not None and getattr(weather, key, None) is not None
            },
        }
        baseline = predict_region_risk(
            observations=[observation], horizon_hours=payload.forecast_hours,
            as_of=point.captured_at, model_version=payload.model_version,
        )
        probability = baseline.probability
        confidence = baseline.confidence
        level = baseline.level
        if level == "unknown":
            level = "low"
        obj = RiskPrediction(
            patrol_id=patrol_id, capture_point_id=point.id,
            observation_key=f"patrol-{patrol_id}/point-{point.seq}", target_event=payload.target_event,
            forecast_hours=payload.forecast_hours, forecast_start=point.captured_at,
            forecast_end=point.captured_at + timedelta(hours=payload.forecast_hours),
            probability=probability, level=level, trend=baseline.trend,
            confidence=confidence, model_version=payload.model_version,
            evidence={"source": "point-analysis", "analyzer_version": analysis.analyzer_version,
                      "risk_score": analysis.risk_score, "features": detail,
                      "prediction_evidence": list(baseline.evidence),
                      "feature_values": dict(baseline.feature_values),
                      "recheck_window_hours": list(baseline.recheck_window_hours),
                      "limitations": ["首版为启发式区域代理，待病种数据训练与独立评估"]},
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
    if db.get(Field, payload.field_id) is None:
        raise HTTPException(status_code=404, detail="地块不存在")
    if payload.patrol_id is not None:
        patrol = db.get(Patrol, payload.patrol_id)
        if patrol is None:
            raise HTTPException(status_code=404, detail="巡检不存在")
        if patrol.field_id != payload.field_id:
            raise HTTPException(status_code=422, detail="任务地块与巡检不一致")
    stmt = select(RiskPrediction).join(Patrol, RiskPrediction.patrol_id == Patrol.id).where(
        RiskPrediction.status == "open", Patrol.field_id == payload.field_id,
    )
    if payload.patrol_id is not None:
        stmt = stmt.where(RiskPrediction.patrol_id == payload.patrol_id)
    predictions = list(db.scalars(stmt.order_by(RiskPrediction.probability.desc()).limit(payload.limit)).all())
    candidates: list[ActiveLearningCandidate] = []
    prediction_by_id: dict[str, RiskPrediction] = {}
    for prediction in predictions:
        point = prediction.capture_point
        if point is None:
            continue
        candidate_id = f"risk-{prediction.id}"
        prediction_by_id[candidate_id] = prediction
        candidates.append(ActiveLearningCandidate(
            candidate_id=candidate_id, quality=prediction.confidence,
            uncertainty=1.0 - prediction.confidence, risk=prediction.probability,
            change=1.0 if prediction.trend == "rising" else 0.0,
            representativeness=0.5, cost=1.0,
        ))
    ranked = select_active_learning_tasks(candidates, SelectionConstraints(max_tasks=payload.limit, budget=float(payload.limit)))
    output: list[RevisitTask] = []
    for row in ranked:
        prediction = prediction_by_id[row.candidate_id]
        point = prediction.capture_point
        if point is None:
            continue
        existing = db.scalar(select(RevisitTask).where(
            RevisitTask.risk_prediction_id == prediction.id,
            # 同一预测只保留一条复巡任务；新预测窗口会生成新的 prediction id。
        ))
        if existing is not None:
            output.append(existing)
            continue
        field_id = payload.field_id
        obj = RevisitTask(
            field_id=field_id, patrol_id=prediction.patrol_id, capture_point_id=prediction.capture_point_id,
            risk_prediction_id=prediction.id,
            task_type=row.task_type, priority=row.score, value_score=row.score,
            rationale={"risk": prediction.probability, "uncertainty": 1.0 - prediction.confidence,
                       "trend": prediction.trend, "reasons": list(row.reasons), "signals": row.signals},
            parameters={"target_event": prediction.target_event, "forecast_hours": prediction.forecast_hours},
            created_by=payload.created_by,
        )
        db.add(obj)
        output.append(obj)
    prediction_ids = [obj.risk_prediction_id for obj in output if obj.risk_prediction_id is not None]
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if not prediction_ids:
            raise
        output = list(db.scalars(select(RevisitTask).where(
            RevisitTask.risk_prediction_id.in_(prediction_ids),
        )).all())
    for obj in output:
        db.refresh(obj)
    return output


@router.get("/devices/{device_id}/tasks/next", response_model=RevisitTaskOut | None)
def next_device_task(device_id: int, db: Session = Depends(get_db)):
    if db.get(Device, device_id) is None:
        raise HTTPException(status_code=404, detail="设备不存在")
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
        freeze_dataset_version(db, obj, now=_now())
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
    if payload.dataset_version_id and db.get(DatasetVersion, payload.dataset_version_id) is None:
        raise HTTPException(status_code=404, detail="数据集版本不存在")
    obj = ModelEvaluation(**payload.model_dump())
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
