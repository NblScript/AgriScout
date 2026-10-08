"""计划 0016 B3：布局、按里程推算株号、标签校正。仓库根目录运行 ``python -m unittest rover.test_positioning``。"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from rover import acquire, hardware, positioning
from rover.point_store import PointStore

ROW = positioning.RowLayout(row_no=1, plants=10, spacing_m=0.4, start_chainage_m=0.5)


class _SlippingOdometer:
    """真实位置在第 n 株，里程计因打滑只读到 90%。"""

    def __init__(self, row: positioning.RowLayout) -> None:
        self.row = row
        self.plant = 0

    def distance_m(self) -> float:
        self.plant += 1
        return round(self.row.chainage_of(self.plant) * 0.9, 3)


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 8, 6, 0, tzinfo=timezone(timedelta(hours=8)))

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


class LayoutTests(unittest.TestCase):
    def test_plant_number_from_chainage(self) -> None:
        self.assertEqual(ROW.chainage_of(1), 0.5)
        self.assertEqual(ROW.chainage_of(10), 4.1)
        self.assertEqual([ROW.plant_at(c) for c in (0.5, 0.65, 0.75, 4.1)], [1, 1, 2, 10])
        self.assertIsNone(ROW.plant_at(0.0))   # 第 1 株之前
        self.assertIsNone(ROW.plant_at(4.6))   # 最后一株之后

    def test_layout_validation_and_example(self) -> None:
        for bad in ({"rows": []}, {"rows": [{"row_no": 1, "plants": 3}]},
                    {"rows": [{"row_no": 1, "plants": 3, "spacing_m": 0}]},
                    {"rows": [{"row_no": 1, "plants": 3, "spacing_m": 0.4}, {"row_no": 1, "plants": 2, "spacing_m": 0.4}]},
                    [{"row_no": 1}]):
            with self.subTest(layout=bad), self.assertRaises(ValueError):
                positioning.parse_layout(bad)
        rows = positioning.load_layout(Path(positioning.__file__).with_name("layout.example.json"))
        self.assertEqual([(r.row_no, r.plants, r.spacing_m) for r in rows], [(1, 30, 0.4), (2, 30, 0.4)])
        self.assertEqual(positioning.pick_row(rows, 2).row_no, 2)
        self.assertIs(positioning.pick_row(rows, None), rows[0])
        with self.assertRaises(ValueError):
            positioning.pick_row(rows, 7)

    def test_key_helpers(self) -> None:
        self.assertEqual(positioning.plant_key(3, 17), "R03-P017")
        self.assertEqual(positioning.parse_key("R03-P017"), (3, 17))
        self.assertIsNone(positioning.parse_key("R00-P001"))
        self.assertIsNone(positioning.parse_key("pole-7"))
        self.assertTrue(positioning.valid_key("pole-7"))
        self.assertFalse(positioning.valid_key("http://x y"))
        self.assertFalse(positioning.valid_key(None))


class PositionerTests(unittest.TestCase):
    def test_tag_corrects_later_plants(self) -> None:
        odometer = _SlippingOdometer(ROW)
        plain = positioning.Positioner(ROW, odometer_source="encoder")
        corrected = positioning.Positioner(ROW, odometer_source="encoder")
        readings = [odometer.distance_m() for _ in range(8)]
        # 不校正：打滑误差越积越大，第 5 株起推成了前一株
        self.assertEqual([plain.estimate(d)["observation_key"] for d in readings],
                         ["R01-P001", "R01-P002", "R01-P003", "R01-P004", "R01-P004", "R01-P005", "R01-P006",
                          "R01-P007"])
        # 第 5 株读到标签：以标签为准，偏差 = 2.1 − 1.89
        fix = corrected.apply_tag("R01-P005", readings[4])
        self.assertEqual(fix, {"route_chainage_m": 2.1, "observation_key": "R01-P005", "position_source": "tag",
                               "offset_m": 0.21})
        later = [corrected.estimate(d) for d in readings[5:]]
        self.assertEqual([f["observation_key"] for f in later], ["R01-P006", "R01-P007", "R01-P008"])
        self.assertEqual({f["position_source"] for f in later}, {"encoder"})

    def test_custom_or_other_row_tag_keeps_offset_and_bad_tag_is_ignored(self) -> None:
        positioner = positioning.Positioner(ROW, offset_m=0.1)
        self.assertEqual(positioner.apply_tag("pole-7", 1.0),
                         {"route_chainage_m": 1.1, "observation_key": "pole-7", "position_source": "tag",
                          "offset_m": 0.1})
        self.assertEqual(positioner.apply_tag("R02-P003", 1.0)["observation_key"], "R02-P003")
        self.assertEqual(positioner.offset_m, 0.1)
        self.assertIsNone(positioner.apply_tag("not a key!", 1.0))
        self.assertIsNone(positioning.Positioner(None).estimate(1.0)["observation_key"])
        with self.assertRaises(ValueError):
            positioning.Positioner(ROW, odometer_source="gnss")


class RunStopsPositioningTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = PointStore.create(self._tmp.name, "trip", {
            "field_id": 1, "device": "t", "started_at": "2026-10-08T06:00:00+08:00"})

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_stops_use_tag_correction_and_keep_offset_after_resume(self) -> None:
        views = acquire.parse_views([{"side": "upper", "pitch_deg": 0}, {"side": "under", "pitch_deg": 35}])
        odometer = _SlippingOdometer(ROW)
        # 每 10 次读一次才读到标签：第 5 个停车点叶背那张读到 R01-P005
        rig = acquire.Rig(hardware.FakeCamera(64, 48), hardware.FakeGimbal(), hardware.FakeLight(),
                          hardware.FakeTagReader(["R01-P005"], every=10))

        def run(stops: int) -> list[dict]:
            return acquire.run_stops(
                self.store, rig, views, odometer, stops=stops, base_lng=116.1, base_lat=39.1,
                policy=acquire.ShootPolicy(), clock=_Clock(), log=lambda _msg: None,
                positioner=positioning.Positioner(ROW, odometer_source="encoder"), distance_source="encoder",
            )

        run(5)
        stop4 = [p for p in self.store.points if p["stop"] == 4]
        # 正面那张还是推算值（P004），读到标签的叶背起改用标签
        self.assertEqual([(p["observation_key"], p["position_source"]) for p in stop4],
                         [("R01-P004", "encoder"), ("R01-P005", "tag")])
        self.assertEqual(stop4[1]["route_chainage_m"], 2.1)
        self.assertEqual(stop4[1]["distance_m"], 1.89)
        # 组包时同一停车点统一取标签结果
        package = self.store.build_package("pkg")
        self.assertEqual({p["observation_key"] for p in package["capture_points"] if p["seq"] in (8, 9)}, {"R01-P005"})

        # 断电后续拍：新定位器从记下的偏差接着推，第 6、7 株不再推错
        reopened = PointStore(self.store.directory)
        reopened.resume()
        self.store = reopened
        odometer.plant = 0
        points = run(7)
        later = [p for p in points if p["stop"] >= 5 and p["view_index"] == 0]
        self.assertEqual([p["observation_key"] for p in later], ["R01-P006", "R01-P007"])
        self.assertEqual({p["distance_source"] for p in points}, {"encoder"})


if __name__ == "__main__":
    unittest.main()
