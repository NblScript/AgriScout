"""平台侧图像质量 ``iq-rule-v1``（计划 0016 阶段 A6）。

与车端 ``rover/quality.py`` 同一公式、各写一份（红线 6：采集端只走 HTTP，不共享代码），
由 ``tests/test_image_quality.py`` 与 ``rover/test_acquire.py`` 用同一组合成图锁成一致；
改公式必须两边一起改。后端只依赖 Pillow（没有 numpy/opencv）。

分析器无关：runner 对每个分析的点都写入 ``detail["image_quality"]``，用 ``method`` 字段追溯版本，
``analyzer_version`` 不变。
"""
import io
from dataclasses import dataclass
from typing import Any

from PIL import Image, ImageFilter, ImageOps, ImageStat

METHOD = "iq-rule-v1"
TARGET_LONG_SIDE = 320  # 只缩不放：长边超过 320 才缩小
_LAPLACIAN = ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1, offset=128)


@dataclass(frozen=True)
class QualityThresholds:
    """判定阈值，与车端同值；均为经验初值，待试拍校准。"""

    min_sharpness: float = 40.0
    max_clip_high: float = 0.05
    max_clip_low: float = 0.20
    backlit_top_minus_center: float = 60.0
    backlit_center_max: float = 70.0


DEFAULT_THRESHOLDS = QualityThresholds()


def assess_image_quality(image: bytes, thresholds: QualityThresholds = DEFAULT_THRESHOLDS) -> dict[str, Any]:
    """返回 ``{method, sharpness, mean_luma, clip_high, clip_low, backlit, ok, reasons}``；解不开抛 OSError。"""
    with Image.open(io.BytesIO(image)) as raw:
        gray = ImageOps.exif_transpose(raw).convert("L")
    if max(gray.size) > TARGET_LONG_SIDE:
        scale = TARGET_LONG_SIDE / max(gray.size)
        gray = gray.resize(
            (max(1, round(gray.width * scale)), max(1, round(gray.height * scale))),
            Image.Resampling.BILINEAR,
        )
    width, height = gray.size
    hist = gray.histogram()
    total = width * height
    clip_high = sum(hist[250:]) / total
    clip_low = sum(hist[:6]) / total
    mean_luma = ImageStat.Stat(gray).mean[0] / 255

    # Pillow 卷积不处理最外一圈像素（原样保留），只统计内圈，避免纯色图测出虚假清晰度
    laplacian = gray.filter(_LAPLACIAN)
    if width > 2 and height > 2:
        laplacian = laplacian.crop((1, 1, width - 1, height - 1))
    sharpness = ImageStat.Stat(laplacian).var[0]

    top = ImageStat.Stat(gray.crop((0, 0, width, max(1, height // 3)))).mean[0]
    center = ImageStat.Stat(gray.crop((
        width // 3, height // 3,
        max(width // 3 + 1, 2 * width // 3), max(height // 3 + 1, 2 * height // 3),
    ))).mean[0]
    backlit = (top - center) >= thresholds.backlit_top_minus_center and center < thresholds.backlit_center_max

    reasons = [
        reason for reason, failed in (
            ("blurry", sharpness < thresholds.min_sharpness),
            ("overexposed", clip_high > thresholds.max_clip_high),
            ("underexposed", clip_low > thresholds.max_clip_low),
            ("backlit", backlit),
        ) if failed
    ]
    return {
        "method": METHOD,
        "sharpness": round(sharpness, 3),
        "mean_luma": round(mean_luma, 4),
        "clip_high": round(clip_high, 4),
        "clip_low": round(clip_low, 4),
        "backlit": backlit,
        "ok": not reasons,
        "reasons": reasons,
    }
