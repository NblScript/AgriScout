"""计划 0016 A4：逐点落盘、断点恢复、组包。仓库根目录运行 ``python -m unittest rover.test_point_store``。"""
from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path

from rover.point_store import POINTS_FILE, PointStore

META = {
    "field_id": 3,
    "planting_id": 5,
    "device": "rover-t",
    "started_at": "2026-10-03T06:00:00+08:00",
    "notes": "rover:rover-t mode=stops",
}


def _point(index: int, stop: int = 0) -> dict:
    return {
        "stop": stop,
        "view_index": 0,
        "distance_m": stop * 0.4,
        "route_chainage_m": stop * 0.4,
        "lng": 116.1,
        "lat": 39.1 + stop * 0.4 / 111_000,
        "captured_at": f"2026-10-03T06:00:{index:02d}+08:00",
        "view": {"side": "upper", "attempt": 1, "accepted": True},
    }


class PointStoreTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.spool = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def test_photo_lands_before_point_line(self) -> None:
        store = PointStore.create(self.spool, "trip", META)
        record = store.append(_point(0), b"jpeg-0")
        self.assertEqual(record["seq"], 0)
        self.assertEqual((store.directory / record["photo_file"]).read_bytes(), b"jpeg-0")
        line = json.loads((store.directory / POINTS_FILE).read_text(encoding="utf-8"))
        self.assertEqual(line["photo_file"], "photos/0.jpg")
        no_photo = store.append(_point(1), None)
        self.assertIsNone(no_photo["photo_file"])
        self.assertEqual(no_photo["seq"], 1)

    def test_interrupted_at_k_points_resumes_k_and_drops_half_line(self) -> None:
        store = PointStore.create(self.spool, "trip", META)
        k = 4
        for index in range(k):
            store.append(_point(index), f"jpeg-{index}".encode())
        # 模拟第 k+1 个点写到一半时断电：照片已落盘，点记录只写了半行
        (store.directory / "photos" / f"{k}.jpg").write_bytes(b"orphan")
        with (store.directory / POINTS_FILE).open("ab") as handle:
            handle.write(b'{"seq": 4, "lng": 116.1, "la')

        reopened = PointStore(store.directory)
        points = reopened.resume()
        self.assertEqual(len(points), k)
        self.assertEqual([p["seq"] for p in points], list(range(k)))
        self.assertEqual(reopened.next_seq, k)
        # 截掉半行后继续追加，文件仍然每行都是完整 JSON
        reopened.append(_point(k), b"jpeg-new")
        lines = (store.directory / POINTS_FILE).read_text(encoding="utf-8").splitlines()
        self.assertEqual([json.loads(line)["seq"] for line in lines], list(range(k + 1)))
        self.assertEqual((store.directory / "photos" / f"{k}.jpg").read_bytes(), b"jpeg-new")

    def test_resume_on_empty_store(self) -> None:
        store = PointStore.create(self.spool, "trip", META)
        self.assertEqual(PointStore(store.directory).resume(), [])

    def test_build_package_is_v1_and_keeps_local_fields_out(self) -> None:
        store = PointStore.create(self.spool, "trip", META)
        store.append(_point(0, stop=0), b"jpeg-0")
        store.append(_point(1, stop=0), None)
        store.append(_point(2, stop=1), b"jpeg-2")
        package = store.build_package()
        header = package["patrol"]
        self.assertEqual(header["field_id"], 3)
        self.assertEqual(header["planting_id"], 5)
        self.assertEqual(header["started_at"], META["started_at"])
        self.assertEqual(header["ended_at"], "2026-10-03T06:00:02+08:00")
        self.assertEqual(len(header["track"]), 2)  # 同一停车点的多张只记一个轨迹点
        points = package["capture_points"]
        self.assertEqual([p["seq"] for p in points], [0, 1, 2])
        self.assertEqual(base64.b64decode(points[0]["photo"]), b"jpeg-0")
        self.assertIsNone(points[1]["photo"])
        self.assertEqual(
            set(points[0]), {"seq", "distance_m", "lng", "lat", "captured_at", "photo", "weather"},
        )

    def test_build_package_needs_points_and_end_after_start(self) -> None:
        store = PointStore.create(self.spool, "trip", META)
        with self.assertRaises(ValueError):
            store.build_package()
        same_time = {**_point(0), "captured_at": META["started_at"]}
        store.append(same_time, b"x")
        self.assertEqual(store.build_package()["patrol"]["ended_at"], "2026-10-03T06:00:01+08:00")

    def test_unfinished_lists_trip_dirs_only_and_remove_cleans_up(self) -> None:
        (self.spool / "abc.json").write_text("{}", encoding="utf-8")  # PackageSpool 的队列文件
        (self.spool / "stray").mkdir()
        first = PointStore.create(self.spool, "a-trip", META)
        PointStore.create(self.spool, "b-trip", META)
        self.assertEqual([p.name for p in PointStore.unfinished(self.spool)], ["a-trip", "b-trip"])
        first.remove()
        self.assertEqual([p.name for p in PointStore.unfinished(self.spool)], ["b-trip"])
        with self.assertRaises(FileExistsError):
            PointStore.create(self.spool, "b-trip", META)


if __name__ == "__main__":
    unittest.main()
