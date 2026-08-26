"""地块与轨迹几何：米制局部坐标 → 经纬度（简单等距圆柱近似，演示足够）。"""
from __future__ import annotations

import math
from dataclasses import dataclass

M_PER_DEG_LAT = 111_320.0


@dataclass(slots=True)
class Layout:
    """一块矩形模拟田的行走布局。"""

    rows: int                 # 垄数
    row_length_m: float       # 垄长
    row_spacing_m: float      # 垄间距
    step_m: float = 0.5       # 采样步长（项目核心节拍）
    origin_lat: float = 39.100
    origin_lng: float = 116.100


def lng_scale(lat0: float) -> float:
    """该纬度下每经度对应的米数。"""
    return M_PER_DEG_LAT * math.cos(math.radians(lat0))


def s_path(layout: Layout) -> list[tuple[float, float, float]]:
    """S 形（往复）行走路径上的采样点。

    返回 [(x_m 东向, y_m 北向, 里程 m), ...]；含垄端换行过渡点。
    """
    pts: list[tuple[float, float, float]] = []
    dist = 0.0
    n_steps = max(1, round(layout.row_length_m / layout.step_m))

    for r in range(layout.rows):
        x = r * layout.row_spacing_m
        forward = r % 2 == 0
        for i in range(n_steps + 1):
            frac = i / n_steps
            y = frac * layout.row_length_m if forward else layout.row_length_m - frac * layout.row_length_m
            pts.append((x, y, dist))
            dist += layout.step_m
        if r < layout.rows - 1:
            # 换行横移：从当前垄头平移到下一垄，距离按步长累计
            next_x = (r + 1) * layout.row_spacing_m
            y_end = layout.row_length_m if forward else 0.0
            span = next_x - x
            k = max(1, round(span / layout.step_m))
            for j in range(1, k + 1):
                pts.append((x + span * j / k, y_end, dist))
                dist += layout.step_m
    return pts


def to_lng_lat(x_m: float, y_m: float, layout: Layout) -> tuple[float, float]:
    return (
        layout.origin_lng + x_m / lng_scale(layout.origin_lat),
        layout.origin_lat + y_m / M_PER_DEG_LAT,
    )


def boundary_geojson(layout: Layout, margin_m: float = 2.0) -> dict:
    """地块边界：布局外扩 margin 的矩形 GeoJSON Polygon。"""
    width = layout.rows * layout.row_spacing_m
    length = layout.row_length_m
    x0, y0 = -margin_m, -margin_m
    x1, y1 = width + margin_m, length + margin_m
    ring = [
        [x0, y0], [x1, y0], [x1, y1], [x0, y1], [x0, y0],
    ]
    ring = [[layout.origin_lng + px / lng_scale(layout.origin_lat),
             layout.origin_lat + py / M_PER_DEG_LAT] for px, py in ring]
    return {"type": "Polygon", "coordinates": [ring]}


def area_ha(layout: Layout) -> float:
    width = layout.rows * layout.row_spacing_m
    return round(width * layout.row_length_m / 10_000.0, 4)
