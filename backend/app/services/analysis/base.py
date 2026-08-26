"""Analyzer 协议与公共类型（主计划 §7.2 契约）。

业务层只依赖本模块的 Analyzer 协议；占位实现 → YOLO → 端侧量化，
替换实现零改业务（接口抽象可替换原则）。
"""
import colorsys
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Any, Protocol

# ---------- 上下文与结果 ----------


@dataclass(slots=True)
class CaptureContext:
    """分析时可见的采样点上下文。"""

    captured_at: datetime
    lng: float
    lat: float
    sowing_date: date | None = None          # 来自 Planting
    crop_name: str | None = None             # 来自 Crop
    crop_stages: list[dict[str, Any]] = field(default_factory=list)  # [{name,days}]


@dataclass(slots=True)
class AnalysisResult:
    """单点分析产出，字段与 analyses 表一一对应。"""

    growth_stage: dict[str, Any] | None = None
    vigor_level: int | None = None           # 1-5
    ndvi: float | None = None                # 占位实现=绿色覆盖率代理
    disease_detections: list[dict[str, Any]] | None = None
    risk_score: float | None = None          # 0-1
    detail: dict[str, Any] = field(default_factory=dict)


class Analyzer(Protocol):
    """图像识别接口：bytes 进、结构化结果出。"""

    version: str

    def analyze(self, image: bytes, context: CaptureContext) -> AnalysisResult: ...


# ---------- 日历法生育期（确定性，非 AI）----------


def calendar_growth_stage(context: CaptureContext) -> dict[str, Any] | None:
    """按播种日期 + 作物生育期表推算当前生育期。

    占位阶段最可靠的"识别"其实是日历——小麦生育期高度可预测。
    返回 {"name","probability","days_in_stage","day_after_sowing","source"}；
    缺播种日期/生育期表或尚未播种时返回 None。
    """
    if context.sowing_date is None or not context.crop_stages:
        return None
    days = (context.captured_at.date() - context.sowing_date).days
    if days < 0:
        return None
    cursor = 0
    current = context.crop_stages[-1]
    for stage in context.crop_stages:
        span = int(stage.get("days", 0))
        if days < cursor + span:
            current = stage
            break
        cursor += span
        current = stage  # 超出末段则停在最后一个生育期
    return {
        "name": current.get("name"),
        "probability": 1.0,
        "days_in_stage": max(days - cursor, 0),
        "day_after_sowing": days,
        "source": "calendar",
    }


# ---------- 颜色分类工具（占位实现共用）----------


def rgb_to_hsv_deg(r: int, g: int, b: int) -> tuple[float, float, float]:
    """RGB(0-255) → (H 0-360°, S 0-1, V 0-1)。"""
    h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    return h * 360, s, v


def classify_pixel_hsv(h: float, s: float, v: float) -> str:
    """粗粒度像素分类：vegetation 绿色植被 / stress 黄化褐化胁迫 / other。

    阈值为经验值（占位算法），后续 YOLO 替换后此函数随版本退役。
    """
    if v < 0.12:  # 过暗（阴影/夜拍）
        return "other"
    if 70 <= h <= 170 and s >= 0.15:
        return "vegetation"
    if 15 <= h <= 65 and s >= 0.25 and v >= 0.2:  # 黄化/枯黄/褐色斑
        return "stress"
    return "other"
