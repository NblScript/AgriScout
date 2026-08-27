"""Stats 大屏聚合统计 DTO。"""
from datetime import datetime

from pydantic import BaseModel


class RecentPatrolStat(BaseModel):
    patrol_id: int
    field_name: str | None = None
    started_at: datetime
    point_count: int
    analyzed_points: int
    avg_ndvi: float | None = None
    avg_risk_score: float | None = None
    # 键为长势等级 "1"-"5"，缺级不计入
    vigor_distribution: dict[str, int]
    stress_points: int


class StatsOverview(BaseModel):
    fields: int
    crops: int
    plantings: int
    devices: int
    patrols: int
    capture_points: int
    analyzed_points: int
    annotations: int
    advices_total: int
    advices_suggested: int
    advices_accepted: int
    advices_rejected: int
    recent_patrols: list[RecentPatrolStat]
