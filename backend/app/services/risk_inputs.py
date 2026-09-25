"""风险预测的区域级输入：把同一观察区域的多日期观测串成时间序列（执行计划 0008，审查第 19 项）。

旧实现每个采样点只输入本次一条观测，趋势恒为 unknown，多日期数据用不上。这里：
- 用 ``region_association`` 把本次和历史巡检的采样点映射到同一套区域网格；
- 每趟巡检在每个区域聚合成一条观测：视觉风险取区域内各点风险分的**最大值**
  （早期病斑是局部的，均值会被健康点稀释），环境取均值；
- 历史只取本次巡检之前、回看窗口内的巡检，杜绝用未来信息（申报书 8.3）。
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutil import to_utc
from app.models import Analysis, CapturePoint, Patrol, WeatherSample
from app.services.region_association import METHOD, FieldGrid

_ENV_KEYS = ("temp_c", "humidity_pct", "light_lux", "wind_mps", "rain_mm", "soil_moisture_pct")


@dataclass(slots=True)
class RegionSeries:
    """一个观察区域：本次巡检的聚合观测 + 按时间排序的历史观测。"""

    key: str
    current: dict[str, Any]
    history: list[dict[str, Any]] = field(default_factory=list)
    history_patrol_ids: list[int] = field(default_factory=list)
    points_in_region: int = 0

    @property
    def observations(self) -> list[dict[str, Any]]:
        return [*self.history, self.current]


def _aggregate(rows: list[tuple[Analysis, CapturePoint, WeatherSample | None]]) -> dict[str, Any]:
    scores = [a.risk_score for a, _, _ in rows if a.risk_score is not None]
    detections = [d for a, _, _ in rows for d in (a.disease_detections or [])]
    env: dict[str, float] = {}
    for key in _ENV_KEYS:
        values = [getattr(w, key) for _, _, w in rows if w is not None and getattr(w, key) is not None]
        if values:
            env[key] = sum(values) / len(values)
    observation: dict[str, Any] = {
        "captured_at": min(to_utc(p.captured_at) for _, p, _ in rows),
        "risk_score": max(scores) if scores else None,
        "environment": env,
        "points": len(rows),
    }
    if detections:
        observation["disease_detections"] = detections
    return observation


def _analysis_rows(db: Session, *conditions) -> list[tuple[Analysis, CapturePoint, WeatherSample | None]]:
    stmt = (
        select(Analysis, CapturePoint, WeatherSample)
        .join(CapturePoint, Analysis.capture_point_id == CapturePoint.id)
        .outerjoin(WeatherSample, WeatherSample.capture_point_id == CapturePoint.id)
        .where(*conditions)
    )
    return [tuple(row) for row in db.execute(stmt).all()]  # type: ignore[misc]


@dataclass(slots=True)
class RegionInputs:
    """一趟巡检的区域级输入。

    series 只含本次巡检有分析结果的区域；history 含回看窗口内出现过的所有区域
    （某区域这趟没照片时，它作为邻居的「上一趟」分数仍然要算，训练与上线才一致）。
    """

    point_key: dict[int, str]
    series: dict[str, RegionSeries]
    grid: FieldGrid
    history: dict[str, list[tuple[int, dict[str, Any]]]] = field(default_factory=dict)


def build_region_series(
    db: Session,
    patrol: Patrol,
    *,
    cell_m: float,
    history_days: int,
) -> RegionInputs:
    """本次巡检各区域的聚合观测 + 回看窗口内历史巡检的区域观测（只取更早的巡检）。"""
    grid = FieldGrid.from_boundary(patrol.field_id, patrol.field.boundary, cell_m)

    current_rows = _analysis_rows(db, Analysis.patrol_id == patrol.id)
    point_key: dict[int, str] = {}
    current_groups: dict[str, list] = defaultdict(list)
    for row in current_rows:
        key = grid.key(row[1].lng, row[1].lat)
        point_key[row[1].id] = key
        current_groups[key].append(row)
    if not current_rows:
        return RegionInputs(point_key, {}, grid)

    first_capture = min(to_utc(row[1].captured_at) for row in current_rows)
    since: datetime = first_capture - timedelta(days=history_days)
    history_rows = _analysis_rows(
        db,
        CapturePoint.patrol_id != patrol.id,
        CapturePoint.patrol_id.in_(select(Patrol.id).where(Patrol.field_id == patrol.field_id)),
        CapturePoint.captured_at >= since,
        CapturePoint.captured_at < first_capture,
    ) if history_days > 0 else []

    history_groups: dict[str, dict[int, list]] = defaultdict(lambda: defaultdict(list))
    for row in history_rows:
        history_groups[grid.key(row[1].lng, row[1].lat)][row[1].patrol_id].append(row)
    history = {
        key: sorted(((pid, _aggregate(rows)) for pid, rows in by_patrol.items()),
                    key=lambda item: (item[1]["captured_at"], item[0]))
        for key, by_patrol in history_groups.items()
    }

    series: dict[str, RegionSeries] = {}
    for key, rows in current_groups.items():
        past = history.get(key, [])
        series[key] = RegionSeries(
            key=key,
            current=_aggregate(rows),
            history=[obs for _, obs in past],
            history_patrol_ids=[pid for pid, _ in past],
            points_in_region=len(rows),
        )
    return RegionInputs(point_key, series, grid, history)


def region_evidence(series: RegionSeries, grid: FieldGrid) -> dict[str, Any]:
    """写入预测 evidence 的区域溯源信息。"""
    return {
        "key": series.key,
        "method": METHOD,
        "cell_m": grid.cell_m,
        "points_in_region": series.points_in_region,
        "region_risk_score": series.current.get("risk_score"),
        "history_patrol_ids": series.history_patrol_ids,
        "history_risk_scores": [obs.get("risk_score") for obs in series.history],
    }
