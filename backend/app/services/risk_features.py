"""风险模型的图像/时空特征（纯函数）：离线重放训练和线上预测共用同一实现（执行计划 0009）。

训练时和上线时各算一遍特征，是训练—上线偏差最常见的来源；这里只保留一份实现，
并由测试锁住两边对同一数据算出的特征完全一致。

输入是「(区域, 巡检) → 区域内风险分最大值」的观测表：巡检用任意可排序的标识（离线用天数，线上用巡检 id），
由调用方给出按时间排序、已按回看窗口截断的更早巡检列表。缺观测（该区域那趟没有可分析的照片）按 0 处理，
变化量在缺上一趟时按「无变化」处理。
"""
from __future__ import annotations

from collections.abc import Hashable, Mapping, Sequence

IMAGE_FEATURES: tuple[str, ...] = ("img_now", "img_hist_max", "img_delta", "nbr_now", "nbr_delta")
DEFAULT_LOOKBACK_DAYS = 30


def neighbor_map(regions: Mapping[str, tuple[int, int]]) -> dict[str, list[str]]:
    """区域 → 周围 8 个网格里存在的区域（按网格坐标）。"""
    by_cell = {cell: key for key, cell in regions.items()}
    return {
        key: [
            by_cell[(ix + dx, iy + dy)]
            for dx in (-1, 0, 1) for dy in (-1, 0, 1)
            if (dx, dy) != (0, 0) and (ix + dx, iy + dy) in by_cell
        ]
        for key, (ix, iy) in regions.items()
    }


def image_features(
    image_score: Mapping[tuple[str, Hashable], float],
    earlier: Sequence[Hashable],
    current: Hashable,
    region: str,
    neighbors: Sequence[str],
) -> dict[str, float]:
    """一个区域在一趟巡检时的 5 个特征。earlier 按时间升序，最后一个即「上一趟」。"""
    prev = earlier[-1] if earlier else None
    now = image_score.get((region, current), 0.0)
    prev_value = image_score.get((region, prev), now) if prev is not None else now
    nbr_now = max((image_score.get((n, current), 0.0) for n in neighbors), default=0.0)
    nbr_prev = (
        max((image_score.get((n, prev), 0.0) for n in neighbors), default=0.0)
        if prev is not None else nbr_now
    )
    return {
        "img_now": now,
        "img_hist_max": max((image_score.get((region, t), 0.0) for t in earlier), default=0.0),
        "img_delta": now - prev_value,
        "nbr_now": nbr_now,
        "nbr_delta": nbr_now - nbr_prev,
    }
