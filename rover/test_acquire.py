"""计划 0016 A1–A3、A5、A7：质量判断、视角补拍、停车模式。

仓库根目录运行 ``python -m unittest rover.test_acquire``；不需要摄像头和后端。
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import math
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

from PIL import Image, ImageDraw, ImageFilter

from rover import acquire, hardware, quality
from rover import run as rover_run
from rover.point_store import PointStore

TZ = timezone(timedelta(hours=8))


# ---- 与 backend/tests/test_image_quality.py 一致的合成图（改这里必须同步改那边）----


def _checkerboard() -> Image.Image:
    image = Image.new("L", (320, 240), 60)
    draw = ImageDraw.Draw(image)
    for y in range(0, 240, 8):
        for x in range(0, 320, 8):
            if (x // 8 + y // 8) % 2:
                draw.rectangle([x, y, x + 7, y + 7], fill=200)
    return image


def _synthetic() -> dict[str, Image.Image]:
    overexposed = Image.new("L", (320, 240), 255)
    overexposed.paste(128, (107, 80, 213, 160))
    backlit = Image.new("L", (320, 240), 40)
    backlit.paste(250, (0, 0, 320, 80))
    return {
        "sharp": _checkerboard(),
        "blurry": _checkerboard().filter(ImageFilter.GaussianBlur(4)),
        "overexposed": overexposed,
        "dark": Image.new("L", (320, 240), 3),
        "backlit": backlit,
    }


EXPECTED = {
    "sharp": dict(sharpness=6977.336, mean_luma=0.5098, clip_high=0.0, clip_low=0.0, backlit=False, reasons=[]),
    "blurry": dict(sharpness=4.498, mean_luma=0.5098, clip_high=0.0, clip_low=0.0, backlit=False, reasons=["blurry"]),
    "overexposed": dict(
        sharpness=157.701, mean_luma=0.945, clip_high=0.8896, clip_low=0.0, backlit=False, reasons=["overexposed"],
    ),
    "dark": dict(
        sharpness=0.0, mean_luma=0.0118, clip_high=0.0, clip_low=1.0, backlit=False,
        reasons=["blurry", "underexposed"],
    ),
    "backlit": dict(
        sharpness=136.609, mean_luma=0.4314, clip_high=0.3333, clip_low=0.0, backlit=True,
        reasons=["overexposed", "backlit"],
    ),
}


def _png(image: Image.Image) -> bytes:
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")
    return buffer.getvalue()


class QualityConsistencyTests(unittest.TestCase):
    def test_synthetic_images_match_shared_expectations(self) -> None:
        images = _synthetic()
        for name, expected in EXPECTED.items():
            with self.subTest(image=name):
                result = quality.assess(_png(images[name]))
                self.assertEqual(result["method"], quality.METHOD)
                # 容差：sharpness 相对 1%，其余 1e-3（计划 0016 A7）
                self.assertTrue(
                    math.isclose(result["sharpness"], expected["sharpness"], rel_tol=0.01, abs_tol=0.01),
                    result["sharpness"],
                )
                for key in ("mean_luma", "clip_high", "clip_low"):
                    self.assertAlmostEqual(result[key], expected[key], delta=1e-3, msg=key)
                self.assertIs(result["backlit"], expected["backlit"])
                self.assertEqual(result["reasons"], expected["reasons"])
                self.assertIs(result["ok"], not expected["reasons"])

    def test_fake_camera_kinds_trigger_their_reason(self) -> None:
        camera = hardware.FakeCamera(640, 480, ["normal", "blurry", "overexposed", "dark", "backlit"])
        reasons = [quality.assess(camera.capture())["reasons"] for _ in range(5)]
        self.assertEqual(reasons[0], [])
        self.assertIn("blurry", reasons[1])
        self.assertIn("overexposed", reasons[2])
        self.assertIn("underexposed", reasons[3])
        self.assertIn("backlit", reasons[4])
        # 脚本用完后一直是合格图
        self.assertTrue(quality.assess(camera.capture())["ok"])

    def test_failure_record_shape(self) -> None:
        record = quality.failure("capture_error: x")
        self.assertFalse(record["ok"])
        self.assertIsNone(record["sharpness"])
        self.assertEqual(record["reasons"], ["capture_error: x"])


class _Clock:
    def __init__(self) -> None:
        self.now = datetime(2026, 10, 3, 6, 0, tzinfo=TZ)

    def __call__(self) -> datetime:
        self.now += timedelta(seconds=1)
        return self.now


VIEWS = acquire.parse_views([
    {"name": "front", "side": "upper", "pitch_deg": 0, "height_m": 0.6},
    {"name": "under-35", "side": "under", "pitch_deg": 35, "height_m": 0.2, "fill_light": True},
])
POSITION = {"distance_m": 0.0, "route_chainage_m": 0.0, "lng": 116.1, "lat": 39.1, "position_source": "estimated"}


class ShootTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.store = PointStore.create(self._tmp.name, "trip", {
            "field_id": 1, "device": "t", "started_at": "2026-10-03T06:00:00+08:00",
        })

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _rig(self, script=(), fail_on=(), tags=("R01-P001",)) -> acquire.Rig:
        return acquire.Rig(
            camera=hardware.FakeCamera(320, 240, script, fail_on=fail_on),
            gimbal=hardware.FakeGimbal(),
            light=hardware.FakeLight(),
            tag_reader=hardware.FakeTagReader(tags),
        )

    def _shoot(self, rig: acquire.Rig, policy=acquire.ShootPolicy()) -> list[dict]:
        return acquire.shoot_stop(self.store, rig, VIEWS, stop=0, position=POSITION, policy=policy, clock=_Clock())

    def test_all_good_one_attempt_per_view(self) -> None:
        rig = self._rig()
        shot = self._shoot(rig)
        self.assertEqual([(p["view_index"], p["view"]["attempt"], p["view"]["accepted"]) for p in shot],
                         [(0, 1, True), (1, 1, True)])
        self.assertEqual(shot[0]["observation_key"], "R01-P001")
        self.assertEqual(shot[1]["observation_key"], "R01-P001")
        self.assertEqual(shot[1]["tags"], [])  # 读到标签后本停车点不再读
        self.assertEqual(shot[0]["position_source"], "estimated")
        self.assertIsNone(shot[0]["reshoot_reason"])

    def test_blurry_under_view_reshoots_with_higher_pitch_until_limit(self) -> None:
        rig = self._rig(script=["normal", "blurry", "blurry", "blurry"])
        shot = self._shoot(rig)
        under = [p for p in shot if p["view_index"] == 1]
        self.assertEqual([p["view"]["attempt"] for p in under], [1, 2, 3])
        self.assertEqual([p["view"]["pitch_deg"] for p in under], [35, 40, 45])
        self.assertTrue(all(not p["view"]["accepted"] for p in under))
        self.assertEqual([p["view"]["quality"]["reasons"] for p in under], [["blurry"]] * 3)
        self.assertEqual([p["reshoot_reason"] for p in under], [None, None, "max_attempts"])
        self.assertEqual(rig.gimbal.moves, [(0, 0), (35, 0), (40, 0), (45, 0)])
        # 每次尝试都落成一个点，照片都在
        self.assertEqual(len(self.store.points), 4)
        self.assertTrue(all(p["photo_file"] for p in self.store.points))

    def test_reshoot_stops_once_accepted_and_upper_view_keeps_pitch(self) -> None:
        rig = self._rig(script=["overexposed", "normal", "backlit", "normal"])
        shot = self._shoot(rig)
        self.assertEqual([p["view"]["quality"]["reasons"] for p in shot],
                         [["blurry", "overexposed"], [], ["overexposed", "backlit"], []])
        self.assertEqual([p["view"]["pitch_deg"] for p in shot], [0, 0, 35, 40])
        self.assertEqual([p["view"]["accepted"] for p in shot], [False, True, False, True])

    def test_fill_light_only_during_under_view(self) -> None:
        rig = self._rig()
        self._shoot(rig)
        self.assertEqual(rig.light.states, [True, False])
        self.assertFalse(rig.light.on)

    def test_capture_exception_records_photo_less_point_and_continues(self) -> None:
        rig = self._rig(fail_on=[1, 2, 3])  # 正面视角三次全部拍照失败
        shot = self._shoot(rig)
        front = [p for p in shot if p["view_index"] == 0]
        self.assertEqual(len(front), 3)
        self.assertTrue(all(p["photo_file"] is None for p in front))
        self.assertTrue(front[0]["view"]["quality"]["reasons"][0].startswith("capture_error: RuntimeError"))
        self.assertEqual(front[-1]["reshoot_reason"], "max_attempts")
        # 后面的视角照常拍；没拍到照片不读标签
        self.assertEqual(shot[-1]["view_index"], 1)
        self.assertTrue(shot[-1]["view"]["accepted"])
        self.assertEqual(shot[-1]["observation_key"], "R01-P001")

    def test_light_is_switched_off_even_if_shooting_aborts(self) -> None:
        rig = self._rig()

        class _Broken(hardware.FakeGimbal):
            def move(self, pitch_deg, yaw_deg):
                if pitch_deg == 35:
                    raise KeyboardInterrupt
                super().move(pitch_deg, yaw_deg)

        rig.gimbal = _Broken()
        with self.assertRaises(KeyboardInterrupt):
            self._shoot(rig)
        self.assertFalse(rig.light.on)

    def test_view_validation(self) -> None:
        with self.assertRaises(ValueError):
            acquire.parse_views([{"side": "left", "pitch_deg": 0}])
        with self.assertRaises(ValueError):
            acquire.parse_views([{"side": "under", "pitch_deg": 95}])
        with self.assertRaises(ValueError):
            acquire.parse_views([{"side": "under"}])
        with self.assertRaises(ValueError):
            acquire.parse_views({"views": []})
        example = acquire.load_views(Path(rover_run.__file__).with_name("views.example.json"))
        self.assertEqual([v.side for v in example], ["upper", "under", "under"])
        self.assertEqual([v.pitch_deg for v in example], [0, 35, 50])


class _Interrupt(Exception):
    pass


class RunStopsTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.spool = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _run(self, store, rig, stops=3, step=0.4):
        return acquire.run_stops(
            store, rig, VIEWS, hardware.FakeOdometer(step), stops=stops, base_lng=116.1, base_lat=39.1,
            policy=acquire.ShootPolicy(), clock=_Clock(), log=lambda _msg: None,
        )

    def test_positions_follow_odometer(self) -> None:
        store = PointStore.create(self.spool, "trip", {"field_id": 1, "device": "t", "started_at": "x"})
        rig = acquire.Rig(hardware.FakeCamera(320, 240), hardware.FakeGimbal(), hardware.FakeLight(),
                          hardware.FakeTagReader(["R01-P001", "R01-P002", "R01-P003"]))
        points = self._run(store, rig)
        self.assertEqual(len(points), 6)
        self.assertEqual([p["distance_m"] for p in points[::2]], [0.0, 0.4, 0.8])
        self.assertEqual([p["observation_key"] for p in points[::2]], ["R01-P001", "R01-P002", "R01-P003"])
        self.assertAlmostEqual(points[-1]["lat"], 39.1 + 0.8 / 111_000, places=7)

    def test_resume_after_interruption_skips_finished_views(self) -> None:
        store = PointStore.create(self.spool, "trip", {"field_id": 1, "device": "t", "started_at": "x"})
        moves = {"n": 0}

        class _DiesOnFifthMove(hardware.FakeGimbal):
            def move(self, pitch_deg, yaw_deg):
                moves["n"] += 1
                if moves["n"] == 5:
                    raise _Interrupt
                super().move(pitch_deg, yaw_deg)

        # 第二个停车点的叶背视角第一次不合格，第二次补拍前断电
        rig = acquire.Rig(hardware.FakeCamera(320, 240, ["normal", "normal", "normal", "blurry"]),
                          _DiesOnFifthMove(), hardware.FakeLight(), None)
        with self.assertRaises(_Interrupt):
            self._run(store, rig)
        self.assertEqual(len(store.points), 4)

        reopened = PointStore(store.directory)
        reopened.resume()
        gimbal = hardware.FakeGimbal()
        rig2 = acquire.Rig(hardware.FakeCamera(320, 240), gimbal, hardware.FakeLight(), None)
        points = self._run(reopened, rig2)
        # 续拍：从第二个停车点叶背视角的第 2 次开始（仰角 +5°），然后拍第三个停车点
        self.assertEqual(gimbal.moves, [(40, 0), (0, 0), (35, 0)])
        stop1_under = [p for p in points if p["stop"] == 1 and p["view_index"] == 1]
        self.assertEqual([p["view"]["attempt"] for p in stop1_under], [1, 2])
        self.assertEqual(stop1_under[-1]["distance_m"], 0.4)
        self.assertEqual([p["seq"] for p in points], list(range(7)))


class _FakeClient:
    instances: list["_FakeClient"] = []

    def __init__(self, *_args, **_kwargs) -> None:
        self.ingested: list[dict] = []
        self.closed = False
        _FakeClient.instances.append(self)

    def get(self, path: str):
        assert path == "/api/v1/health"
        return {"version": "t", "environment": "test", "database": "memory"}

    def ensure_device(self, code, name):
        return {"id": 1, "code": code}

    def ensure_field(self, name, boundary):
        return {"id": 2}

    def ensure_crop(self, *args):
        return {"id": 3}

    def ensure_planting(self, field_id, crop_id, sowing):
        return {"id": 4}

    def media_exists(self, sha256):
        return {"exists": False, "url": None}

    def upload_media(self, data, content_type):
        return {"url": f"/media/{hashlib.sha256(data).hexdigest()}.jpg", "created": True}

    def ingest(self, package):
        self.ingested.append(package)
        n = len(package["capture_points"])
        return {"patrol_id": 9, "capture_points": n, "photos_saved": 0, "photos_referenced": n}

    def close(self) -> None:
        self.closed = True


class StopsModeRunTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.spool = Path(self._tmp.name)
        _FakeClient.instances = []

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _main(self, *extra: str) -> int:
        with patch.object(rover_run, "ApiClient", _FakeClient), contextlib.redirect_stdout(io.StringIO()):
            return rover_run.main([
                "--api", "http://stops.invalid", "--fake", "--mode", "stops", "--interval", "0",
                "--spool-dir", str(self.spool), *extra,
            ])

    def test_fake_stops_run_uploads_every_attempt_and_cleans_up(self) -> None:
        result = self._main("--stops", "2", "--fake-script", "normal,blurry")
        self.assertEqual(result, 0)
        package = _FakeClient.instances[0].ingested[0]
        # 2 个停车点 × 3 个视角，其中一个叶背视角补拍了一次
        self.assertEqual(len(package["capture_points"]), 7)
        self.assertTrue(all(p["photo"] for p in package["capture_points"]))
        self.assertEqual(package["patrol"]["planting_id"], 4)
        self.assertIn("mode=stops", package["patrol"]["notes"])
        self.assertEqual(list(self.spool.iterdir()), [])  # 队列和逐点目录都清空了

    def test_interrupted_trip_is_packaged_on_next_run(self) -> None:
        store = PointStore.create(self.spool, "rover-001-old", {
            "field_id": 2, "planting_id": 4, "device": "rover-001",
            "started_at": "2026-10-03T05:00:00+08:00", "notes": "old",
        })
        store.append({**POSITION, "stop": 0, "view_index": 0,
                      "captured_at": "2026-10-03T05:00:05+08:00", "view": {}}, b"jpeg")
        PointStore.create(self.spool, "rover-001-empty", {"field_id": 2, "device": "x", "started_at": "y"})
        result = self._main("--flush-spool")
        self.assertEqual(result, 0)
        uploaded = _FakeClient.instances[0].ingested
        self.assertEqual(len(uploaded), 1)
        self.assertEqual(uploaded[0]["patrol"]["notes"], "old")
        self.assertEqual(PointStore.unfinished(self.spool), [])

    def test_resume_flag_continues_latest_trip(self) -> None:
        with patch.object(acquire, "run_stops", side_effect=_Interrupt), \
                patch.object(rover_run, "ApiClient", _FakeClient), self.assertRaises(_Interrupt), \
                contextlib.redirect_stdout(io.StringIO()):
            rover_run.main([
                "--api", "http://stops.invalid", "--fake", "--mode", "stops", "--stops", "2",
                "--interval", "0", "--spool-dir", str(self.spool),
            ])
        self.assertEqual(len(PointStore.unfinished(self.spool)), 1)
        result = self._main("--resume", "--stops", "9")  # 续拍沿用建档时的 2 个停车点
        self.assertEqual(result, 0)
        package = _FakeClient.instances[-1].ingested[0]
        self.assertEqual(len(package["capture_points"]), 6)
        self.assertEqual(PointStore.unfinished(self.spool), [])

    def test_real_hardware_not_wired_fails_clearly_without_leaving_trip_dir(self) -> None:
        output = io.StringIO()
        with patch.object(rover_run, "ApiClient", _FakeClient), contextlib.redirect_stdout(output):
            result = rover_run.main([
                "--api", "http://stops.invalid", "--mode", "stops", "--spool-dir", str(self.spool),
            ])
        self.assertIn("云台驱动尚未接入", output.getvalue())
        self.assertEqual(result, 1)
        self.assertEqual(PointStore.unfinished(self.spool), [])
        self.assertFalse(_FakeClient.instances[0].ingested)

    def test_stops_arguments_are_validated(self) -> None:
        for bad in (["--stops", "0"], ["--max-attempts", "0"], ["--stop-spacing", "0"],
                    ["--fake-script", "normal,fuzzy"]):
            with self.subTest(args=bad), self.assertRaises(SystemExit), \
                    patch("sys.stderr", io.StringIO()):
                rover_run.parse_args(["--mode", "stops", *bad])


if __name__ == "__main__":
    unittest.main()
