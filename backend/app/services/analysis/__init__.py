"""分析引擎包：协议、占位实现、YOLO 实现、后台执行器。

ANALYZER_BACKEND=placeholder|yolo 环境变量切换（默认占位，测试零依赖）。
"""
from functools import lru_cache

from app.core.config import get_settings
from app.services.analysis.base import (
    AnalysisResult,
    Analyzer,
    CaptureContext,
    calendar_growth_stage,
)
from app.services.analysis.placeholder_color import PlaceholderColorAnalyzer
from app.services.analysis.yolo_detector import YoloAnalyzer

_singleton = PlaceholderColorAnalyzer()


@lru_cache
def _yolo_singleton(model_path: str) -> YoloAnalyzer:
    return YoloAnalyzer(model_path)


def get_analyzer() -> Analyzer:
    """FastAPI 依赖：按配置分派识别引擎（测试可 override）。"""
    settings = get_settings()
    if settings.analyzer_backend == "yolo":
        return _yolo_singleton(settings.yolo_model_path)
    return _singleton


__all__ = [
    "AnalysisResult",
    "Analyzer",
    "CaptureContext",
    "PlaceholderColorAnalyzer",
    "YoloAnalyzer",
    "calendar_growth_stage",
    "get_analyzer",
]
