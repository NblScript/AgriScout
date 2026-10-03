"""车端图像质量判断 ``iq-rule-v1``（计划 0016 阶段 A）。

只用 Pillow，便于在树莓派上逐张判断、不合格就补拍。后端
``backend/app/services/analysis/image_quality.py`` 按同一公式各写一份（红线 6
禁止共享代码），两边用同一组合成测试图把结果锁成一致；改公式必须两边一起改。
"""
from __future__ import annotations

import io
from dataclasses import dataclass

from PIL import Image, ImageFilter, ImageOps, ImageStat

METHOD = "iq-rule-v1"
TARGET_LONG_SIDE = 320  # 只缩不放：长边超过 320 才缩小，小图保持原尺寸
_LAPLACIAN = ImageFilter.Kernel((3, 3), [0, 1, 0, 1, -4, 1, 0, 1, 0], scale=1, offset=128)


@dataclass(frozen=True)
class QualityThresholds:
    """判定阈值。全部为经验初值，待试拍校准（计划 0013「参数与阈值」）。"""

    min_sharpness: float = 40.0        # 拉普拉斯响应方差下限；待试拍校准
    max_clip_high: float = 0.05        # 灰度 ≥250 像素占比上限；待试拍校准
    max_clip_low: float = 0.20         # 灰度 ≤5 像素占比上限；待试拍校准
    backlit_top_minus_center: float = 60.0  # 上三分之一均值 − 中央格均值（0–255）；待试拍校准
    backlit_center_max: float = 70.0   # 中央格均值上限（0–255）；待试拍校准


DEFAULT_THRESHOLDS = QualityThresholds()


def _prepare(data: bytes) -> Image.Image:
    with Image.open(io.BytesIO(data)) as raw:
        gray = ImageOps.exif_transpose(raw).convert("L")
    long_side = max(gray.size)
    if long_side > TARGET_LONG_SIDE:
        scale = TARGET_LONG_SIDE / long_side
        size = (max(1, round(gray.width * scale)), max(1, round(gray.height * scale)))
        gray = gray.resize(size, Image.Resampling.BILINEAR)
    return gray


def _region_mean(gray: Image.Image, box: tuple[int, int, int, int]) -> float:
    return ImageStat.Stat(gray.crop(box)).mean[0]


def assess(data: bytes, thresholds: QualityThresholds = DEFAULT_THRESHOLDS) -> dict:
    """返回 ``{method, sharpness, mean_luma, clip_high, clip_low, backlit, ok, reasons}``。

    解不开的图片抛 ``OSError``（Pillow 的 UnidentifiedImageError 是其子类），由调用方记录。
    """
    gray = _prepare(data)
    width, height = gray.size
    total = width * height
    hist = gray.histogram()
    mean_luma = ImageStat.Stat(gray).mean[0] / 255
    clip_high = sum(hist[250:]) / total
    clip_low = sum(hist[:6]) / total
    # Pillow 的卷积不处理最外一圈像素（原样保留），纯色图会因此测出虚假的「清晰」，所以只统计内圈
    edges = gray.filter(_LAPLACIAN)
    if width > 2 and height > 2:
        edges = edges.crop((1, 1, width - 1, height - 1))
    sharpness = ImageStat.Stat(edges).var[0]
    top = _region_mean(gray, (0, 0, width, max(1, height // 3)))
    # 中央九宫格；极小图（边长 <3）也至少取 1 像素
    center = _region_mean(gray, (
        width // 3, height // 3,
        max(width // 3 + 1, 2 * width // 3), max(height // 3 + 1, 2 * height // 3),
    ))
    backlit = (top - center) >= thresholds.backlit_top_minus_center and center < thresholds.backlit_center_max

    reasons: list[str] = []
    if sharpness < thresholds.min_sharpness:
        reasons.append("blurry")
    if clip_high > thresholds.max_clip_high:
        reasons.append("overexposed")
    if clip_low > thresholds.max_clip_low:
        reasons.append("underexposed")
    if backlit:
        reasons.append("backlit")
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


def failure(reason: str) -> dict:
    """拍照失败或图片解不开时的质量记录：指标为空，``ok=false``。"""
    return {
        "method": METHOD,
        "sharpness": None,
        "mean_luma": None,
        "clip_high": None,
        "clip_low": None,
        "backlit": None,
        "ok": False,
        "reasons": [reason],
    }
