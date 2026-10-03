"""计划 0014：模拟器 --v2 的株号推导。仓库根目录运行 ``python -m unittest simulator.test_geo_v2``。"""
from __future__ import annotations

import unittest

from simulator.geo import Layout, plant_key, s_path


class PlantKeyTests(unittest.TestCase):
    def test_row_points_get_recommended_keys_and_turns_do_not(self) -> None:
        layout = Layout(rows=2, row_length_m=1.0, row_spacing_m=1.0, step_m=0.5)
        keys = [plant_key(x, y, layout) for x, y, _ in s_path(layout)]
        self.assertEqual(keys[:3], [("R01-P001", 0.0), ("R01-P002", 0.5), ("R01-P003", 1.0)])
        # 第二垄往回走：株序号按行内位置算，与行走方向无关
        self.assertEqual(keys[-3:], [("R02-P003", 1.0), ("R02-P002", 0.5), ("R02-P001", 0.0)])

    def test_turn_between_rows_has_no_key(self) -> None:
        layout = Layout(rows=2, row_length_m=1.0, row_spacing_m=1.5, step_m=0.5)
        self.assertIsNone(plant_key(0.5, 1.0, layout))
        self.assertEqual(plant_key(1.5, 1.0, layout), ("R02-P003", 1.0))


if __name__ == "__main__":
    unittest.main()
