"""线上复巡任务生成（``POST /revisit-tasks/generate``，计划 0015 从路由层下沉）。

与离线重放 H2 的「联合策略」用同一实现（``active_learning.revisit_candidate`` / ``select_revisits``）：
1. 全部 open 预测按区域（``observation_key``）去重，每个区域取概率最高的一条，全量参与排序；
   修掉了旧逻辑「先按概率截前 limit 条再排序、代表性写死 0.5、同一区域重复入选」（技术债台账）。
2. 每个区域的信号：
   - 风险 p：启发式预测取概率；risk-lr 按模型自己的 high 阈值归一（罕见事件概率绝对值很小，D13）。
   - 变化：risk-lr 证据里的本区域 / 邻域图像增量；启发式取本趟区域风险分减上一趟（没有邻域增量，记 0）。
   - 陈旧程度：距这个区域上次完成复巡的天数，按 3 个巡检间隔归一；从没复巡过记 1。
   - 质量：本趟这个区域的照片里质量合格的比例（0016-A 的 ``image_quality``）；
     老数据没有质量记录时退回 D13 口径（启发式用置信度，risk-lr 用证据质量）。
3. 只按 revisit 打分取前 limit 个区域，生成 revisit 任务；同一预测只保留一条任务。
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.timeutil import to_utc
from app.models import ObservationUnit, Patrol, RevisitTask, RiskPrediction
from app.services.active_learning import revisit_candidate, select_revisits
from app.services.observation_units import unit_region_key
from app.services.risk_model import is_lr_version
from app.services.risk_prediction import DEFAULT_QUALITY

STRATEGY = "joint-revisit"


def _days(value) -> float:
    return to_utc(value).timestamp() / 86400


def d13_quality(prediction: RiskPrediction) -> float:
    """D13 口径的质量信号：启发式的置信度本身就是证据充分度；risk-lr 的置信度是 |2p−1|，改读证据质量。"""
    if is_lr_version(prediction.model_version):
        return ((prediction.evidence or {}).get("evidence_quality") or {}).get("score", DEFAULT_QUALITY)
    return prediction.confidence


def risk_value(prediction: RiskPrediction) -> float:
    """风险 p：risk-lr 按模型 high 阈值归一，使 high 等级正好对应 p ≥ 0.5（D13）。"""
    if is_lr_version(prediction.model_version):
        high = (((prediction.evidence or {}).get("model") or {}).get("level_thresholds") or {}).get("high")
        if high:
            return min(1.0, prediction.probability / (2 * high))
    return prediction.probability


def deltas(prediction: RiskPrediction) -> tuple[float, float]:
    """(本区域图像风险增量, 邻域增量)。"""
    evidence = prediction.evidence or {}
    values = evidence.get("feature_values") or {}
    if "img_delta" in values:
        return float(values["img_delta"]), float(values.get("nbr_delta", 0.0))
    region = evidence.get("region") or {}
    now, history = region.get("region_risk_score"), region.get("history_risk_scores") or []
    if now is None or not history or history[-1] is None:
        return 0.0, 0.0
    return float(now) - float(history[-1]), 0.0


def image_quality(group: list[RiskPrediction]) -> float | None:
    """同一区域同一趟的照片里质量合格的比例；没有任何质量记录时返回 None。"""
    flags = []
    for prediction in group:
        quality = ((prediction.evidence or {}).get("features") or {}).get("image_quality")
        if isinstance(quality, dict) and isinstance(quality.get("ok"), bool):
            flags.append(quality["ok"])
    return sum(flags) / len(flags) if flags else None


def _last_revisits(db: Session, field_id: int, keys: set[str]) -> dict[str, float]:
    """区域键 → 最近一次完成的复巡（天，epoch 起算）；预测挂的任务和巡检计划按株挂的任务都算。"""
    last: dict[str, float] = {}

    def note(key: str | None, completed_at) -> None:
        if key in keys and completed_at is not None:
            last[key] = max(last.get(key, float("-inf")), _days(completed_at))

    done = select(RevisitTask).where(
        RevisitTask.field_id == field_id, RevisitTask.task_type == "revisit", RevisitTask.status == "completed",
    )
    for task, key in db.execute(
        done.add_columns(RiskPrediction.observation_key)
        .join(RiskPrediction, RevisitTask.risk_prediction_id == RiskPrediction.id)
    ).all():
        note(key, task.completed_at)
    for task, unit_key in db.execute(
        done.add_columns(ObservationUnit.key)
        .join(ObservationUnit, RevisitTask.observation_unit_id == ObservationUnit.id)
    ).all():
        note(unit_region_key(field_id, unit_key), task.completed_at)
    return last


def region_candidates(
    db: Session, field_id: int, patrol_id: int | None, interval_days: float,
) -> tuple[list[Any], dict[str, RiskPrediction], dict[str, dict[str, Any]]]:
    """(候选, 区域键 → 代表预测, 区域键 → 信号来源说明)。"""
    stmt = select(RiskPrediction).join(Patrol, RiskPrediction.patrol_id == Patrol.id).where(
        RiskPrediction.status == "open", Patrol.field_id == field_id, RiskPrediction.capture_point_id.is_not(None),
    )
    if patrol_id is not None:
        stmt = stmt.where(RiskPrediction.patrol_id == patrol_id)
    groups: dict[tuple[str, int], list[RiskPrediction]] = defaultdict(list)
    best: dict[str, RiskPrediction] = {}
    for prediction in db.scalars(stmt.order_by(RiskPrediction.id)):
        groups[(prediction.observation_key, prediction.patrol_id)].append(prediction)
        current = best.get(prediction.observation_key)
        rank = (prediction.probability, _days(prediction.forecast_start), prediction.id)
        if current is None or rank > (current.probability, _days(current.forecast_start), current.id):
            best[prediction.observation_key] = prediction
    last_visit = _last_revisits(db, field_id, set(best))
    candidates, sources = [], {}
    for key in sorted(best):
        prediction = best[key]
        measured = image_quality(groups[(key, prediction.patrol_id)])
        quality = measured if measured is not None else d13_quality(prediction)
        image_delta, neighbor_delta = deltas(prediction)
        candidates.append(revisit_candidate(
            key, probability=risk_value(prediction), image_delta=image_delta, neighbor_delta=neighbor_delta,
            day=_days(prediction.forecast_start), last_visit_day=last_visit.get(key),
            interval_days=interval_days, quality=quality,
        ))
        sources[key] = {
            "quality_source": "image_quality" if measured is not None else "d13",
            "last_revisit_days_ago": (None if key not in last_visit
                                      else round(_days(prediction.forecast_start) - last_visit[key], 3)),
        }
    return candidates, best, sources


def generate_revisit_tasks(
    db: Session, *, field_id: int, patrol_id: int | None, limit: int, created_by: str, interval_days: float = 1.0,
) -> list[RevisitTask]:
    candidates, best, sources = region_candidates(db, field_id, patrol_id, interval_days)
    output: list[RevisitTask] = []
    for row in select_revisits(candidates, limit):
        prediction = best[row.candidate_id]
        existing = db.scalar(select(RevisitTask).where(RevisitTask.risk_prediction_id == prediction.id))
        if existing is not None:  # 同一预测只保留一条复巡任务；新预测窗口会生成新的 prediction id
            output.append(existing)
            continue
        point = prediction.capture_point
        task = RevisitTask(
            field_id=field_id, patrol_id=prediction.patrol_id, capture_point_id=prediction.capture_point_id,
            risk_prediction_id=prediction.id, observation_unit_id=point.observation_unit_id if point else None,
            task_type=row.task_type, priority=row.score, value_score=row.score,
            rationale={"strategy": STRATEGY, "region": row.candidate_id, "risk": prediction.probability,
                       "uncertainty": row.signals["uncertainty"], "trend": prediction.trend,
                       "reasons": list(row.reasons), "signals": row.signals, "rank": row.rank,
                       "candidates": len(candidates), **sources[row.candidate_id]},
            parameters={"target_event": prediction.target_event, "forecast_hours": prediction.forecast_hours,
                        "observation_key": prediction.observation_key},
            created_by=created_by,
        )
        db.add(task)
        output.append(task)
    prediction_ids = [task.risk_prediction_id for task in output if task.risk_prediction_id is not None]
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        if not prediction_ids:
            raise
        output = list(db.scalars(select(RevisitTask).where(RevisitTask.risk_prediction_id.in_(prediction_ids))).all())
    for task in output:
        db.refresh(task)
    return output
