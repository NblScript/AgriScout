"""计划 0016 A4：逐点落盘、断点恢复、组包。仓库根目录运行 ``python -m unittest rover.test_point_store``。"""
from __future__ import annotations

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

    def test_build_package_is_v2_metadata_without_photo_bytes(self) -> None:
        # 阶段 B 起组成 v2 元数据包：照片不读进内存，只记本地文件，上传时换成平台 URL
        store = PointStore.create(self.spool, "trip", META)
        store.append({**_point(0, stop=0), "tags": ["junk"]}, b"jpeg-0")
        store.append(_point(1, stop=0), None)
        store.append(_point(2, stop=1), b"jpeg-2")
        package = store.build_package("pkg-1")
        self.assertEqual(package["schema_version"], "2.0")
        header = package["patrol"]
        self.assertEqual(header["client_package_id"], "pkg-1")
        self.assertEqual(header["field_id"], 3)
        self.assertEqual(header["planting_id"], 5)
        self.assertEqual(header["started_at"], META["started_at"])
        self.assertEqual(header["ended_at"], "2026-10-03T06:00:02+08:00")
        self.assertEqual(len(header["track"]), 2)  # 同一停车点的多张只记一个轨迹点
        points = package["capture_points"]
        self.assertEqual([p["seq"] for p in points], [0, 1, 2])
        self.assertEqual([(p["photo"], p["photo_file"]) for p in points],
                         [(None, "photos/0.jpg"), (None, None), (None, "photos/2.jpg")])
        self.assertEqual(set(points[0]), {
            "seq", "distance_m", "lng", "lat", "captured_at", "photo", "photo_file", "weather",
            "observation_key", "route_chainage_m", "distance_source", "position_source", "view",
        })
        self.assertEqual(points[0]["view"], {"side": "upper", "attempt": 1, "accepted": True})

    def test_points_of_a_tagged_stop_share_the_tag_position(self) -> None:
        store = PointStore.create(self.spool, "trip", META)
        estimated = {**_point(0), "observation_key": "R01-P002", "position_source": "estimated"}
        tagged = {**_point(1), "observation_key": "R01-P003", "position_source": "tag", "route_chainage_m": 1.3,
                  "lat": 39.2}
        store.append(estimated, b"a")  # 正面先拍，还没读到标签
        store.append(tagged, b"b")     # 叶背读到了标签
        store.append({**_point(2, stop=1), "observation_key": "bad key!", "position_source": "encoder"}, b"c")
        points = store.build_package("pkg")["capture_points"]
        self.assertEqual([(p["observation_key"], p["position_source"], p["route_chainage_m"], p["lat"])
                          for p in points[:2]], [("R01-P003", "tag", 1.3, 39.2)] * 2)
        self.assertIsNone(points[2]["observation_key"])  # 不合平台正则的株号不上传

    def test_build_package_needs_points_and_end_after_start(self) -> None:
        store = PointStore.create(self.spool, "trip", META)
        with self.assertRaises(ValueError):
            store.build_package("pkg")
        same_time = {**_point(0), "captured_at": META["started_at"]}
        store.append(same_time, b"x")
        self.assertEqual(store.build_package("pkg")["patrol"]["ended_at"], "2026-10-03T06:00:01+08:00")

    def test_sealed_trip_is_no_longer_unfinished(self) -> None:
        store = PointStore.create(self.spool, "trip", META)
        store.append(_point(0), b"x")
        store.seal("pkg-9")
        self.assertEqual(PointStore.unfinished(self.spool), [])
        self.assertEqual(PointStore.sealed(self.spool), [(store.directory, "pkg-9")])

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
