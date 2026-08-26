"""分析结果 DTO。"""
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict


class AnalysisOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    capture_point_id: int
    analyzer_version: str
    growth_stage: dict[str, Any] | None = None
    vigor_level: int | None = None
    ndvi: float | None = None
    disease_detections: list[dict[str, Any]] | None = None
    risk_score: float | None = None
    detail: dict[str, Any] | None = None
    analyzed_at: datetime


class PatrolAnalysisSummaryOut(BaseModel):
    """巡检级分析汇总：M4 规则引擎与 M6 面板的数据源。"""

    patrol_id: int
    analysis_status: str
    total_points: int
    analyzed_points: int
    analyzer_version: str | None = None
    vigor_distribution: dict[str, int]      # {"1": n, ...}
    avg_ndvi: float | None = None
    avg_risk_score: float | None = None
    stage_histogram: dict[str, int]         # 生育期 → 点数
    stress_flagged_points: int              # 有胁迫检出的点数
