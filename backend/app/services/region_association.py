"""观察区域关联 v0：地块局部网格分箱（纯函数，决策见执行计划 0008）。

同一块地多次巡检的采样点，落在同一网格就视为同一观察区域，用于把多日期观测串成时间序列、
计算空间邻域。这是过渡方案：适用于模拟器和 RTK 级坐标；巡检包 v2 提供协议级
``observation_key``（垄号 + 桩号，计划 0007 P0-1）后，以协议值为准。

坐标换算用等距圆柱近似：田块尺度（百米级）误差远小于网格边长。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from typing import Any

M_PER_DEG_LAT = 111_320.0
DEFAULT_CELL_M = 2.5
METHOD = "grid-v0"

_KEY_RE = re.compile(r"^field-(\d+)/grid([0-9.]+)m/(-?\d+)_(-?\d+)$")


@dataclass(frozen=True, slots=True)
class FieldGrid:
    """一块地的区域网格：原点取地块边界外包框的西南角。"""

    field_id: int
    origin_lng: float
    origin_lat: float
    cell_m: float = DEFAULT_CELL_M

    @classmethod
    def from_boundary(cls, field_id: int, boundary: dict[str, Any], cell_m: float = DEFAULT_CELL_M) -> "FieldGrid":
        if cell_m <= 0:
            raise ValueError("cell_m 必须为正数")
        try:
            ring = boundary["coordinates"][0]
            lngs = [float(p[0]) for p in ring]
            lats = [float(p[1]) for p in ring]
        except (KeyError, IndexError, TypeError, ValueError) as exc:
            raise ValueError(f"地块 {field_id} 边界无法解析为 Polygon 外环") from exc
        if not lngs:
            raise ValueError(f"地块 {field_id} 边界为空")
        return cls(field_id, min(lngs), min(lats), cell_m)

    def local_xy(self, lng: float, lat: float) -> tuple[float, float]:
        """经纬度 → 以原点为基准的东向/北向米数。"""
        x = (lng - self.origin_lng) * M_PER_DEG_LAT * math.cos(math.radians(self.origin_lat))
        y = (lat - self.origin_lat) * M_PER_DEG_LAT
        return x, y

    def cell(self, lng: float, lat: float) -> tuple[int, int]:
        x, y = self.local_xy(lng, lat)
        # 先按 1e-6 米取整再下取整，避免同一坐标因浮点误差落到相邻网格
        return math.floor(round(x / self.cell_m, 6)), math.floor(round(y / self.cell_m, 6))

    def key_of_cell(self, ix: int, iy: int) -> str:
        return f"field-{self.field_id}/grid{self.cell_m:g}m/{ix}_{iy}"

    def key(self, lng: float, lat: float) -> str:
        return self.key_of_cell(*self.cell(lng, lat))

    def cell_centroid_xy(self, ix: int, iy: int) -> tuple[float, float]:
        return (ix + 0.5) * self.cell_m, (iy + 0.5) * self.cell_m


def parse_key(key: str) -> tuple[int, float, int, int] | None:
    """区域键 → (field_id, cell_m, ix, iy)；不是网格键（如协议提供的键）返回 None。"""
    match = _KEY_RE.match(key)
    if match is None:
        return None
    return int(match[1]), float(match[2]), int(match[3]), int(match[4])


def neighbor_cells(ix: int, iy: int, radius: int = 1) -> list[tuple[int, int]]:
    """切比雪夫距离不超过 radius 的相邻网格（不含自身）。"""
    return [
        (ix + dx, iy + dy)
        for dx in range(-radius, radius + 1)
        for dy in range(-radius, radius + 1)
        if (dx, dy) != (0, 0)
    ]
