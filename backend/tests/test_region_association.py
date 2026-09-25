"""观察区域关联 v0：同一位置跨巡检得到同一区域键；邻域与键解析。"""
import pytest

from app.services.region_association import FieldGrid, neighbor_cells, parse_key

BOUNDARY = {"type": "Polygon", "coordinates": [[[116.1, 39.1], [116.101, 39.1], [116.101, 39.101], [116.1, 39.101], [116.1, 39.1]]]}


def test_same_location_same_key_and_cells_are_metric():
    grid = FieldGrid.from_boundary(7, BOUNDARY, cell_m=2.5)
    key = grid.key(116.1000, 39.1000)
    assert key == "field-7/grid2.5m/0_0"
    # 北向 3 m → 第 2 个网格
    assert grid.cell(116.1000, 39.1 + 3 / 111_320) == (0, 1)
    assert parse_key(key) == (7, 2.5, 0, 0)
    assert parse_key("field-1/row-07/12.5m") is None  # 协议级键不是网格键


def test_float_noise_does_not_split_a_cell_boundary():
    grid = FieldGrid.from_boundary(1, BOUNDARY, cell_m=0.5)
    lat = 39.1 + 1.0 / 111_320  # 恰好 2 个网格边长
    assert grid.cell(116.1, lat) == grid.cell(116.1, lat + 1e-12)


def test_neighbors_and_invalid_boundary():
    assert len(neighbor_cells(0, 0)) == 8 and (0, 0) not in neighbor_cells(0, 0)
    with pytest.raises(ValueError):
        FieldGrid.from_boundary(1, {"type": "Polygon", "coordinates": []})
