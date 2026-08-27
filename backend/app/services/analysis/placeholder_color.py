"""L0 占位识别：颜色统计估长势（主计划 §8.1 级别 L0）。

原理：植被在 HSV 色相环上占据稳定区间；统计绿色覆盖占比即可粗估长势，
黄化/枯褐占比作为胁迫信号。无任何训练依赖，演示与联调够用，
也是将来与 YOLO 结果对比的基线（analyzer_version 锁定可复现）。
"""
from app.services.analysis.base import (
    AnalysisResult,
    Analyzer,
    CaptureContext,
    calendar_growth_stage,
    image_color_stats,
)

# vigor_level 分档阈值（green_ratio 下界），可调常量集中在此便于规则联动
VIGOR_CUTS = ((0.45, 5), (0.35, 4), (0.25, 3), (0.15, 2))  # 其余为 1


class PlaceholderColorAnalyzer:
    """颜色统计占位分析器。version 固化进 Analysis.analyzer_version。"""

    version = "placeholder-color-v0"

    def analyze(self, image: bytes, context: CaptureContext) -> AnalysisResult:
        stats = image_color_stats(image)
        green_ratio = stats["green_ratio"]
        stress_ratio = stats["stress_ratio"]
        mean_luma = stats["mean_luminance"]

        vigor_level = next(
            (level for cut, level in VIGOR_CUTS if green_ratio >= cut), 1,
        )
        # NDVI 代理：真实 NDVI∈[-1,1]，此处仅由绿色占比线性近似，detail 中明确标记
        ndvi_proxy = round(max(-1.0, min(1.0, (green_ratio - 0.18) * 2.4)), 3)
        risk_score = round(
            min(1.0, stress_ratio * 2.5 + max(0.0, 0.22 - green_ratio) * 2.0), 3,
        )

        detections: list[dict] = []
        if stress_ratio >= 0.08:
            detections.append({
                "type": "suspected_stress",
                "label": "叶色异常斑块（疑似胁迫，待人工复核）",
                "confidence": round(min(stress_ratio * 3.0, 0.9), 3),
            })

        return AnalysisResult(
            growth_stage=calendar_growth_stage(context),
            vigor_level=vigor_level,
            ndvi=ndvi_proxy,
            disease_detections=detections or None,
            risk_score=risk_score,
            detail={
                **stats,
                "ndvi_is_proxy": True,
                "low_light": stats["low_light"],
            },
        )
