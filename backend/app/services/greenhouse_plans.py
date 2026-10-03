"""环境读数落库、每株状态汇总、巡检计划生成与落库（计划 0015 的数据库一侧）。

纯计算在 ``greenhouse_env`` / ``plant_state`` / ``patrol_planner`` 里；这里只负责从库里取输入、把计划写成任务。
计划没有单独的表：每条名单项写成一条 ``RevisitTask``（确认→label、补拍→revisit、全覆盖→coverage、抽查→random），
计划头（版本、日期、第几次生成、生成时刻、种子、环境摘要）存在任务的 ``parameters`` 里，「最近一次计划」按生成序号从任务里还原。
重新生成时，上一版里还在排队、这次没入选的计划任务作废，派车队列里只留最新计划的任务。
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.core.timeutil import FIELD_TZ, field_date, to_utc
from app.models import Annotation, CapturePoint, EnvReading, ObservationUnit, RevisitTask
from app.services import greenhouse_env, patrol_planner
from app.services.plant_state import HumanLabel, Observation, PlantState, plant_state
from app.services.risk_model import typed_neighbor_map

OPEN_STATUSES = ("queued", "assigned", "running")
# 计划日的环境截止时刻：计划日当地 08:00（前一夜结束），晚于当前时间时取当前时间
PLAN_ENV_CUTOFF = time(8, 0)
LIST_BY_TASK_TYPE = {task_type: name for name, task_type in patrol_planner.TASK_TYPES.items()}


# ---------------------------------------------------------------- 环境读数


def insert_env_readings(
    db: Session, field_id: int, sensor_key: str, readings: list[dict[str, Any]], *, device_id: int | None, source: str,
) -> tuple[int, int]:
    """同一传感器同一时刻只存一条：本次请求里的重复和库里已有的都跳过。返回 (新增, 跳过)。"""
    unique: dict[datetime, dict[str, Any]] = {}
    for reading in readings:
        unique.setdefault(to_utc(reading["observed_at"]), reading)
    times = sorted(unique)
    existing = set(db.scalars(select(EnvReading.observed_at).where(
        EnvReading.field_id == field_id, EnvReading.sensor_key == sensor_key,
        EnvReading.observed_at >= times[0], EnvReading.observed_at <= times[-1],
    )).all())
    inserted = 0
    for observed_at in times:
        if observed_at in existing:
            continue
        reading = unique[observed_at]
        db.add(EnvReading(
            field_id=field_id, sensor_key=sensor_key, device_id=device_id, observed_at=observed_at,
            temp_c=reading["temp_c"], humidity_pct=reading["humidity_pct"],
            leaf_wetness=reading.get("leaf_wetness"), source=source,
        ))
        inserted += 1
    return inserted, len(readings) - inserted


def load_readings(
    db: Session, field_id: int, since: datetime, until: datetime, sensor_key: str | None = None,
) -> tuple[list[greenhouse_env.Reading], list[str]]:
    stmt = select(EnvReading).where(
        EnvReading.field_id == field_id, EnvReading.observed_at >= since, EnvReading.observed_at < until,
    )
    if sensor_key is not None:
        stmt = stmt.where(EnvReading.sensor_key == sensor_key)
    rows = list(db.scalars(stmt.order_by(EnvReading.observed_at)).all())
    readings = [greenhouse_env.Reading(r.observed_at, r.temp_c, r.humidity_pct, r.leaf_wetness) for r in rows]
    return readings, sorted({r.sensor_key for r in rows})


def latest_reading_time(db: Session, field_id: int) -> datetime | None:
    return db.scalar(select(EnvReading.observed_at).where(EnvReading.field_id == field_id)
                     .order_by(EnvReading.observed_at.desc()).limit(1))


def env_summary(
    db: Session, field_id: int, as_of: datetime, *, plan_date: date | None = None, history_days: int = 7,
    sensor_key: str | None = None,
) -> dict[str, Any]:
    """as_of 前 history_days 天（至少覆盖环境指数的 72 小时）的环境摘要。"""
    days = max(history_days, 4)
    readings, sensors = load_readings(db, field_id, as_of - timedelta(days=days), as_of, sensor_key)
    summary = greenhouse_env.summarize(readings, as_of, plan_date, history_days=days)
    for hour in summary["hourly"]:
        hour["favorable"] = greenhouse_env.is_favorable(hour)
        hour["wet"] = greenhouse_env.is_wet(hour)
    summary["sensors"] = sensors
    return summary


# ---------------------------------------------------------------- 每株状态


@dataclass
class UnitContext:
    unit: ObservationUnit
    state: PlantState
    latest_point: CapturePoint | None
    latest_under_ok_point: CapturePoint | None


def _accepted(point: CapturePoint) -> bool | None:
    """车端结论优先（拍摄当场的判断），没有再用平台按同一公式测的质量。"""
    view = point.view_meta or {}
    if isinstance(view.get("accepted"), bool):
        return view["accepted"]
    quality = ((point.analysis.detail if point.analysis else None) or {}).get("image_quality") or {}
    return quality["ok"] if isinstance(quality.get("ok"), bool) else None


def unit_contexts(db: Session, field_id: int, as_of: datetime) -> list[UnitContext]:
    units = list(db.scalars(select(ObservationUnit).where(
        ObservationUnit.field_id == field_id, ObservationUnit.status == "active",
    ).order_by(ObservationUnit.key)).all())
    if not units:
        return []
    points_by_unit: dict[int, list[CapturePoint]] = defaultdict(list)
    for point in db.scalars(
        select(CapturePoint).options(selectinload(CapturePoint.analysis))
        .where(CapturePoint.observation_unit_id.in_([u.id for u in units]), CapturePoint.captured_at <= as_of)
        .order_by(CapturePoint.captured_at, CapturePoint.id)
    ):
        points_by_unit[point.observation_unit_id].append(point)
    point_unit = {p.id: unit_id for unit_id, points in points_by_unit.items() for p in points}
    labels_by_unit: dict[int, list[HumanLabel]] = defaultdict(list)
    if point_unit:
        for ann in db.scalars(select(Annotation).where(Annotation.capture_point_id.in_(list(point_unit)))):
            labels_by_unit[point_unit[ann.capture_point_id]].append(
                HumanLabel(ann.label, ann.updated_at, ann.annotator_name))
    contexts = []
    for unit in units:
        points = points_by_unit.get(unit.id, [])
        observations = [
            Observation(p.captured_at, (p.view_meta or {}).get("side"), _accepted(p),
                        p.analysis.risk_score if p.analysis else None,
                        p.analysis.analyzer_version if p.analysis else None)
            for p in points
        ]
        under_ok = [p for p in points if (p.view_meta or {}).get("side") == "under" and _accepted(p) is True]
        contexts.append(UnitContext(
            unit=unit, state=plant_state(observations, labels_by_unit.get(unit.id, [])),
            latest_point=points[-1] if points else None,
            latest_under_ok_point=under_ok[-1] if under_ok else None,
        ))
    return contexts


def state_row(ctx: UnitContext) -> dict[str, Any]:
    return {"unit_id": ctx.unit.id, "key": ctx.unit.key, "row_no": ctx.unit.row_no,
            "position_no": ctx.unit.position_no, **ctx.state.as_dict()}


# ---------------------------------------------------------------- 巡检计划


def plan_as_of(plan_date: date, now: datetime) -> datetime:
    return min(to_utc(now), datetime.combine(plan_date, PLAN_ENV_CUTOFF, tzinfo=FIELD_TZ).astimezone(to_utc(now).tzinfo))


def _days_between(later: datetime, earlier: datetime | None) -> float | None:
    return None if earlier is None else round((to_utc(later) - to_utc(earlier)).total_seconds() / 86400, 4)


def planner_inputs(contexts: list[UnitContext], as_of: datetime) -> list[patrol_planner.UnitInput]:
    coords = {ctx.unit.key: ("unit", ctx.unit.row_no, ctx.unit.position_no)
              for ctx in contexts if ctx.unit.row_no is not None and ctx.unit.position_no is not None}
    neighbors = typed_neighbor_map(coords)
    score = {ctx.unit.key: ctx.state.model_score or 0.0 for ctx in contexts}
    return [
        patrol_planner.UnitInput(
            unit_id=ctx.unit.id, key=ctx.unit.key, state=ctx.state,
            days_since_seen=_days_between(as_of, ctx.state.last_seen_at),
            days_since_under_ok=_days_between(as_of, ctx.state.last_under_ok_at),
            neighbor_max_score=max((score[n] for n in neighbors.get(ctx.unit.key, [])), default=0.0),
            row_no=ctx.unit.row_no, position_no=ctx.unit.position_no,
        )
        for ctx in contexts
    ]


def _env_brief(summary: dict[str, Any]) -> dict[str, Any]:
    """存进任务的环境摘要：指数与分量 + 最近几天的逐日指标（小时序列太大，不存）。"""
    return {**summary["index"], "daily": summary["daily"][-4:], "sensors": summary["sensors"]}


def generate_plan(
    db: Session, field_id: int, *, plan_date: date, now: datetime, created_by: str,
    params: patrol_planner.PlannerParams = patrol_planner.DEFAULT_PARAMS,
) -> dict[str, Any]:
    as_of = plan_as_of(plan_date, now)
    summary = env_summary(db, field_id, as_of, plan_date=plan_date)
    contexts = unit_contexts(db, field_id, as_of)
    by_unit = {ctx.unit.id: ctx for ctx in contexts}
    plan = patrol_planner.build_plan(
        planner_inputs(contexts, as_of), summary, plan_date=plan_date,
        seed=patrol_planner.plan_seed(field_id, plan_date), params=params,
    )
    env = {**_env_brief(summary), "env_used": plan["env"]["env_used"], "env_missing": plan["env"]["env_missing"]}
    # 生成序号逐次加一：同一时钟刻度里生成两次也分得清哪次在后
    generation = max((_generation(task) for task in _planner_tasks(db, field_id)), default=0) + 1
    header = {"generation": generation, "generated_at": to_utc(now).isoformat(), "seed": plan["seed"],
              "units": plan["units"], "reshoot_budget": plan["reshoot_budget"], "env": env}
    tasks: dict[tuple[int, str], RevisitTask] = {}
    for name in patrol_planner.LISTS:
        for item in plan["lists"][name]:
            ctx = by_unit[item.unit_id]
            point = ctx.latest_under_ok_point if name == "confirm" and ctx.latest_under_ok_point else ctx.latest_point
            parameters = {
                "plan_version": plan["plan_version"], "plan_date": plan_date.isoformat(), "list_name": name,
                "observation_key": ctx.unit.key, "chainage_m": ctx.unit.chainage_m, "window": plan["window"],
                "plan": header,
            }
            if name == "reshoot":
                parameters["views"] = [dict(v) for v in params.reshoot_views]
            task = db.scalar(select(RevisitTask).where(
                RevisitTask.field_id == field_id, RevisitTask.observation_unit_id == item.unit_id,
                RevisitTask.task_type == item.task_type, RevisitTask.status.in_(OPEN_STATUSES),
                RevisitTask.risk_prediction_id.is_(None),  # 只复用计划任务，不动按预测生成的复巡
            ).order_by(RevisitTask.id.desc()).limit(1))
            if task is None:
                task = RevisitTask(field_id=field_id, observation_unit_id=item.unit_id, task_type=item.task_type,
                                   created_by=created_by)
                db.add(task)
            task.patrol_id = point.patrol_id if point is not None else None
            task.capture_point_id = point.id if point is not None else None
            task.priority = item.priority
            task.value_score = item.score
            task.rationale = _jsonable({**item.rationale, "plan_version": plan["plan_version"]})
            task.parameters = _jsonable(parameters)
            tasks[(item.unit_id, name)] = task
    db.flush()
    _supersede_queued(db, field_id, keep={task.id for task in tasks.values()}, header=header, plan_date=plan_date)
    db.commit()
    for task in tasks.values():
        db.refresh(task)
    return _plan_out(field_id, plan["plan_version"], plan_date, header, plan["window"], [
        (by_unit[unit_id].unit, name, task) for (unit_id, name), task in tasks.items()
    ], params=plan["params"])


def _planner_tasks(db: Session, field_id: int, *statuses: str) -> list[RevisitTask]:
    """本地块由巡检计划写出的任务（按预测生成的复巡任务不算）。"""
    stmt = (select(RevisitTask).options(selectinload(RevisitTask.observation_unit))
            .where(RevisitTask.field_id == field_id, RevisitTask.observation_unit_id.is_not(None),
                   RevisitTask.risk_prediction_id.is_(None)))
    if statuses:
        stmt = stmt.where(RevisitTask.status.in_(statuses))
    return [task for task in db.scalars(stmt) if (task.parameters or {}).get("plan_version")]


def _generation(task: RevisitTask) -> int:
    return int((task.parameters.get("plan") or {}).get("generation") or 0)


def _supersede_queued(db: Session, field_id: int, *, keep: set[int], header: dict[str, Any], plan_date: date) -> None:
    """上一版计划里还在排队、这次没入选的任务作废；已派给车或执行中的不动，由执行方收尾。"""
    for task in _planner_tasks(db, field_id, "queued"):
        if task.id in keep:
            continue
        task.status = "cancelled"
        task.rationale = {**(task.rationale or {}), "superseded_by": {
            "plan_date": plan_date.isoformat(), "generation": header["generation"], "generated_at": header["generated_at"],
        }}


def latest_plan(db: Session, field_id: int) -> dict[str, Any] | None:
    """最近一次计划：生成序号最大的那批计划任务（任务被复用时计划头会改成最新一次）。"""
    rows = _planner_tasks(db, field_id)
    if not rows:
        return None
    last = max(_generation(task) for task in rows)
    batch = [task for task in rows if _generation(task) == last]
    first = batch[0].parameters
    entries = [(task.observation_unit, task.parameters.get("list_name") or LIST_BY_TASK_TYPE[task.task_type], task)
               for task in batch]
    return _plan_out(field_id, first["plan_version"], date.fromisoformat(first["plan_date"]), first["plan"],
                     first.get("window"), entries, params=None)


def _plan_out(field_id, version, plan_date, header, window, entries, *, params) -> dict[str, Any]:
    lists: dict[str, list[dict[str, Any]]] = {name: [] for name in patrol_planner.LISTS}
    for unit, name, task in entries:
        lists[name].append({
            "unit_id": unit.id, "key": unit.key, "row_no": unit.row_no, "position_no": unit.position_no,
            "list_name": name, "task_id": task.id, "task_type": task.task_type, "task_status": task.status,
            "score": task.value_score, "priority": task.priority, "rationale": task.rationale,
        })
    for name, items in lists.items():
        items.sort(key=lambda row: (-row["score"], row["key"]) if name in ("confirm", "reshoot") else row["key"])
    return {"field_id": field_id, "plan_version": version, "plan_date": plan_date,
            "generation": header.get("generation"), "generated_at": header.get("generated_at"), "seed": header["seed"],
            "units": header["units"], "reshoot_budget": header["reshoot_budget"], "env": header["env"],
            "window": window, **lists, "params": params}


def _jsonable(value: Any) -> Any:
    """日期时间转 ISO 字符串，存进 JSON 列。"""
    if isinstance(value, dict):
        return {k: _jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    return value


def today(now: datetime) -> date:
    return field_date(now)
