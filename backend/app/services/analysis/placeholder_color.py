"""L0 占位识别：颜色统计估长势（主计划 §8.1 级别 L0）。

原理：植被在 HSV 色相环上占据稳定区间；统计绿色覆盖占比即可粗估长势，
黄化/枯褐占比作为胁迫信号。无任何训练依赖，演示与联调够用，
也是将来与 YOLO 结果对比的基线（analyzer_version 锁定可复现）。
"""
import io

from PIL import Image

from app.services.analysis.base import (
    AnalysisResult,
    Analyzer,
    CaptureContext,
    calendar_growth_stage,
    classify_pixel_hsv,
    rgb_to_hsv_deg,
)

THUMBNAIL = (64, 64)  # 统计用分辨率，4096 像素纯 Python 循环毫秒级

# vigor_level 分档阈值（green_ratio 下界），可调常量集中在此便于规则联动
VIGOR_CUTS = ((0.45, 5), (0.35, 4), (0.25, 3), (0.15, 2))  # 其余为 1


class PlaceholderColorAnalyzer:
    """颜色统计占位分析器。version 固化进 Analysis.analyzer_version。"""

    version = "placeholder-color-v0"

    def analyze(self, image: bytes, context: CaptureContext) -> AnalysisResult:
        img = Image.open(io.BytesIO(image)).convert("RGB")
        img.thumbnail(THUMBNAIL)
        # load() 返回 PixelAccess（getdata 自 Pillow 12 起弃用）
        access = img.load()
        width, height = img.size
        pixels = [access[x, y] for y in range(height) for x in range(width)]
        total = max(len(pixels), 1)

        counts = {"vegetation": 0, "stress": 0, "other": 0}
        lum_sum = 0
        for r, g, b in pixels:
            counts[classify_pixel_hsv(*rgb_to_hsv_deg(r, g, b))] += 1
            lum_sum += 0.299 * r + 0.587 * g + 0.114 * b

        green_ratio = counts["vegetation"] / total
        stress_ratio = counts["stress"] / total
        mean_luma = lum_sum / total

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
                "green_ratio": round(green_ratio, 4),
                "stress_ratio": round(stress_ratio, 4),
                "mean_luminance": round(mean_luma, 1),
                "ndvi_is_proxy": True,
                "low_light": mean_luma < 30,
                "sample_pixels": total,
            },
        )
