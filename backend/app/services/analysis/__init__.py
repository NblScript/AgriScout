"""分析引擎包：协议、占位实现、后台执行器。M3 占位 → P3 YOLO 只动这里。"""
from app.services.analysis.base import (
    AnalysisResult,
    Analyzer,
    CaptureContext,
    calendar_growth_stage,
)
from app.services.analysis.placeholder_color import PlaceholderColorAnalyzer

_singleton = PlaceholderColorAnalyzer()


def get_analyzer() -> Analyzer:
    """FastAPI 依赖：当前返回占位实现；YOLO 上线时替换此处（测试可 override）。"""
    return _singleton


__all__ = [
    "AnalysisResult",
    "Analyzer",
    "CaptureContext",
    "PlaceholderColorAnalyzer",
    "calendar_growth_stage",
    "get_analyzer",
]
