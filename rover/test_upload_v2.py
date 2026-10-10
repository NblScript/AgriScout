"""计划 0016 B2/B4：照片分步上传、协议 v2 包、重复补传与 409、作物与模式默认值。

用本地 HTTP 假平台（只按接口合同实现，不导入后端）；仓库根目录运行 ``python -m unittest rover.test_upload_v2``。
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import json
import re
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

from rover import run as rover_run
from rover.point_store import PointStore

LAYOUT = str(Path(rover_run.__file__).with_name("layout.example.json"))

# 平台协议 v2 的字段约束（对照 /api/v1/ingest/patrol-schema，在这里按合同手写一份，不导入后端）
KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{0,79}$")
PACKAGE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")
POINT_FIELDS = {"seq", "distance_m", "lng", "lat", "captured_at", "photo", "weather", "observation_key",
                "route_chainage_m", "distance_source", "position_source", "view"}
VIEW_FIELDS = {"side", "pitch_deg", "yaw_deg", "height_m", "fill_light", "attempt", "accepted", "quality"}
CLOCK_FIELDS = {"synced", "source", "offset_s", "measured_at"}
CLOCK_SOURCES = {"chrony", "ntp", "rtc", "gnss", "manual", "unknown"}


def v2_violations(package: dict) -> list[str]:
    problems = []
    if package.get("schema_version") != "2.0":
        problems.append("schema_version")
    if not PACKAGE_ID_RE.match(str(package["patrol"].get("client_package_id", ""))):
        problems.append("client_package_id")
    clock = package["patrol"].get("clock")
    if clock is not None:  # 计划 0007 P0-2：出车时的时钟状态
        if set(clock) - CLOCK_FIELDS or clock.get("source", "unknown") not in CLOCK_SOURCES:
            problems.append("clock")
        if clock.get("synced") not in (None, True, False) or not isinstance(clock.get("offset_s"), (int, float, type(None))):
            problems.append("clock 取值")
    seqs = [p["seq"] for p in package["capture_points"]]
    if len(seqs) != len(set(seqs)) or not seqs:
        problems.append("seq")
    for p in package["capture_points"]:
        where = f"seq {p.get('seq')}"
        if set(p) - POINT_FIELDS:
            problems.append(f"{where} 多余字段 {sorted(set(p) - POINT_FIELDS)}")
        if p.get("observation_key") is not None and not KEY_RE.match(p["observation_key"]):
            problems.append(f"{where} observation_key")
        if p.get("distance_source") not in (None, "encoder", "odometry", "configured", "estimated"):
            problems.append(f"{where} distance_source")
        if p.get("position_source") not in (None, "rtk", "gnss", "tag", "encoder", "estimated", "manual"):
            problems.append(f"{where} position_source")
        if p.get("route_chainage_m") is not None and p["route_chainage_m"] < 0:
            problems.append(f"{where} route_chainage_m")
        if p.get("distance_m", 0) < 0 or not (-180 <= p["lng"] <= 180 and -90 <= p["lat"] <= 90):
            problems.append(f"{where} 位置越界")
        if p.get("photo") is not None and not p["photo"].startswith("/media/"):
            problems.append(f"{where} photo 不是平台 URL")
        view = p.get("view")
        if view is not None:
            if set(view) - VIEW_FIELDS or view.get("side", "unknown") not in ("upper", "under", "unknown"):
                problems.append(f"{where} view")
            if not -90 <= view.get("pitch_deg", 0) <= 90 or not -180 <= view.get("yaw_deg", 0) <= 180:
                problems.append(f"{where} view 角度")
            if view.get("attempt", 1) < 1 or view.get("height_m", 0) < 0:
                problems.append(f"{where} view attempt/height")
            if "quality" in view and not isinstance(view["quality"].get("ok"), bool):
                problems.append(f"{where} view.quality.ok")
    return problems


class _Handler(BaseHTTPRequestHandler):
    server: "_Platform"

    def _json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _body(self) -> bytes:
        return self.rfile.read(int(self.headers.get("Content-Length", "0")))

    def do_GET(self) -> None:  # noqa: N802
        url = urlsplit(self.path)
        platform = self.server
        platform.log.append(("GET", url.path))
        if url.path == "/api/v1/health":
            self._json(200, {"version": "fake", "environment": "test", "database": "memory",
                             "server_time": (datetime.now(timezone.utc) - platform.clock_lag).isoformat()})
        elif url.path == "/api/v1/media/exists":
            digest = parse_qs(url.query)["sha256"][0]
            found = platform.media.get(digest)
            self._json(200, {"exists": found is not None, "url": found})
        elif url.path in {"/api/v1/devices", "/api/v1/fields", "/api/v1/crops", "/api/v1/plantings"}:
            self._json(200, platform.records.get(url.path, []))
        else:
            self._json(404, {"detail": "not found"})

    def do_POST(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        platform = self.server
        platform.log.append(("POST", path))
        if path == "/api/v1/media":
            data = self._body()
            digest = hashlib.sha256(data).hexdigest()
            created = digest not in platform.media
            platform.media[digest] = f"/media/{digest}.jpg"
            platform.uploads.append(self.headers.get("Content-Type"))
            self._json(201 if created else 200, {"url": platform.media[digest], "sha256": digest, "created": created})
            return
        payload = json.loads(self._body())
        if path == "/api/v1/ingest/patrol":
            self._ingest(payload)
            return
        records = platform.records.setdefault(path, [])
        record = {"id": len(records) + 10, **payload}
        records.append(record)
        self._json(201, record)

    def _ingest(self, package: dict) -> None:
        platform = self.server
        platform.ingested.append(package)
        if platform.ingest_status is not None:
            self._json(platform.ingest_status, {"detail": "injected"})
            return
        missing = [p["photo"] for p in package["capture_points"]
                   if p.get("photo") and p["photo"].removeprefix("/media/").removesuffix(".jpg") not in platform.media]
        if missing:
            self._json(422, {"detail": f"照片引用在平台上不存在：{missing[0]}"})
            return
        header = package["patrol"]
        key = (header["device"], header.get("client_package_id"))
        digest = json.dumps(package, sort_keys=True)
        if key in platform.packages:
            patrol_id, earlier = platform.packages[key]
            if earlier != digest:
                self._json(409, {"detail": "包号冲突"})
                return
            self._json(200, {"patrol_id": patrol_id, "capture_points": len(package["capture_points"]),
                             "photos_saved": 0, "photos_referenced": 0, "duplicate": True})
            return
        patrol_id = 100 + len(platform.packages)
        platform.packages[key] = (patrol_id, digest)
        if platform.lose_next_response:  # 平台收下了，回执却在路上丢了
            platform.lose_next_response = False
            self._json(503, {"detail": "gateway timeout"})
            return
        n = len(package["capture_points"])
        self._json(201, {"patrol_id": patrol_id, "capture_points": n, "photos_saved": 0,
                         "photos_referenced": n, "duplicate": False})

    def log_message(self, *_args: object) -> None:
        return


class _Platform(HTTPServer):
    def __init__(self, handler: type[BaseHTTPRequestHandler] = _Handler) -> None:
        super().__init__(("127.0.0.1", 0), handler)
        self.log: list[tuple[str, str]] = []
        self.records: dict[str, list[dict]] = {}
        self.media: dict[str, str] = {}
        self.uploads: list[str | None] = []
        self.ingested: list[dict] = []
        self.packages: dict[tuple, tuple[int, str]] = {}
        self.ingest_status: int | None = None
        self.lose_next_response = False
        self.clock_lag = timedelta(0)  # 平台时间比真实时间慢多少（模拟车端时钟快了）
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)

    def __enter__(self) -> "_Platform":
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.shutdown()
        self.server_close()
        self._thread.join(timeout=2)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}"


class UploadV2Tests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.spool = Path(self._tmp.name)

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _main(self, platform: _Platform, *extra: str, device: str = "rover-v2") -> int:
        with contextlib.redirect_stdout(io.StringIO()):
            return rover_run.main([
                "--api", platform.base_url, "--fake", "--interval", "0", "--width", "64", "--height", "48",
                "--device", device, "--spool-dir", str(self.spool), "--upload-retries", "0", *extra,
            ])

    def _envelopes(self) -> list[dict]:
        return [json.loads(path.read_text(encoding="utf-8")) for path in sorted(self.spool.glob("*.json"))]

    def test_default_run_uploads_photos_first_then_a_valid_v2_package(self) -> None:
        with _Platform() as platform:
            result = self._main(platform, "--layout", LAYOUT, "--stops", "2", "--fake-script", "normal,blurry")
        self.assertEqual(result, 0)
        package = platform.ingested[0]
        self.assertEqual(v2_violations(package), [])
        points = package["capture_points"]
        self.assertEqual(len(points), 7)  # 2 个停车点 × 3 个视角，一个叶背补拍了一次
        # 先传照片、后交包；包里只有 URL，每张照片一个
        posts = [path for method, path in platform.log if method == "POST"]
        self.assertEqual(posts[-8:], ["/api/v1/media"] * 7 + ["/api/v1/ingest/patrol"])
        self.assertEqual(platform.uploads, ["image/jpeg"] * 7)
        self.assertEqual(sorted(p["photo"] for p in points), sorted(platform.media.values()))
        self.assertEqual(package["patrol"]["client_package_id"],
                         rover_run.PackageSpool.package_id(package))
        self.assertEqual([p["observation_key"] for p in points], ["R01-P001"] * 4 + ["R01-P002"] * 3)
        self.assertEqual({(p["position_source"], p["distance_source"]) for p in points}, {("tag", "configured")})
        self.assertEqual(points[0]["route_chainage_m"], 0.5)  # 布局第 1 株的行内位置
        self.assertEqual([p["view"]["attempt"] for p in points if p["view"]["side"] == "under"], [1, 2, 1, 1, 1])
        # 默认作物是黄瓜（生育期占位，待农技复核）
        self.assertEqual(platform.records["/api/v1/crops"][0]["name"], "黄瓜")
        self.assertEqual(list(self.spool.iterdir()), [])  # 队列文件和照片目录都删了

    def test_package_carries_clock_status_measured_against_the_platform(self) -> None:
        """计划 0007 P0-2：出车时量一次与平台的时间差，连同系统对时状态放进包头。"""
        with _Platform() as platform, patch.object(rover_run.clock, "run_command", lambda _cmd: None):
            platform.clock_lag = timedelta(minutes=10)
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                result = rover_run.main([
                    "--api", platform.base_url, "--fake", "--interval", "0", "--width", "64", "--height", "48",
                    "--device", "rover-clock", "--spool-dir", str(self.spool), "--upload-retries", "0", "--stops", "1",
                ])
        self.assertEqual(result, 0)
        package = platform.ingested[0]
        self.assertEqual(v2_violations(package), [])
        clock = package["patrol"]["clock"]
        self.assertEqual((clock["synced"], clock["source"]), (None, "unknown"))
        self.assertAlmostEqual(clock["offset_s"], 600, delta=5)
        self.assertIn("本机比平台快 约 10 分钟", out.getvalue())
        self.assertIn("拍摄时间会不准", out.getvalue())

    def test_photos_already_on_the_platform_are_not_uploaded_again(self) -> None:
        with _Platform() as platform:
            self.assertEqual(self._main(platform, "--stops", "1", device="rover-a"), 0)
            first_uploads = len(platform.uploads)
            # 假相机每趟产出同样的字节：第二趟（另一台车、另一个包）照片全在平台上，只查不传
            self.assertEqual(self._main(platform, "--stops", "1", device="rover-b"), 0)
        self.assertEqual(first_uploads, 3)
        self.assertEqual(len(platform.uploads), 3)
        self.assertEqual(len(platform.ingested), 2)
        self.assertEqual([p["photo"] for p in platform.ingested[0]["capture_points"]],
                         [p["photo"] for p in platform.ingested[1]["capture_points"]])

    def test_lost_response_is_replayed_as_duplicate_and_queue_is_deleted(self) -> None:
        with _Platform() as platform:
            platform.lose_next_response = True
            self.assertEqual(self._main(platform, "--stops", "1"), 1)
            [envelope] = self._envelopes()
            self.assertEqual(envelope["attempts"], 1)
            self.assertTrue((self.spool / envelope["photo_dir"] / "photos").is_dir())  # 照片留到平台确认
            self.assertEqual(self._main(platform, "--flush-spool"), 0)
        self.assertEqual(len(platform.packages), 1)
        self.assertEqual(platform.ingested[0], platform.ingested[1])  # 重传的包一字不差
        self.assertEqual(len(platform.uploads), 3)  # 补传时照片只查不传
        self.assertEqual(list(self.spool.iterdir()), [])

    def test_conflict_is_kept_for_manual_handling_and_skipped_later(self) -> None:
        with _Platform() as platform:
            platform.ingest_status = 409
            self.assertEqual(self._main(platform, "--stops", "1"), 1)
            [envelope] = self._envelopes()
            self.assertTrue(envelope["needs_manual"])
            self.assertIn("409", envelope["last_error"])
            platform.ingest_status = None
            self.assertEqual(self._main(platform, "--flush-spool"), 1)
        self.assertEqual(len(platform.ingested), 1)  # 待人工处理的包不再自动重传
        self.assertEqual(len(self._envelopes()), 1)

    def test_offline_upload_keeps_package_and_photos(self) -> None:
        with _Platform() as platform:
            platform.ingest_status = 503
            self.assertEqual(self._main(platform, "--stops", "1"), 1)
            [envelope] = self._envelopes()
            self.assertFalse(envelope.get("needs_manual", False))
            platform.ingest_status = None
            self.assertEqual(self._main(platform, "--flush-spool"), 0)
        self.assertEqual(list(self.spool.iterdir()), [])

    def test_leftover_photo_dir_of_an_uploaded_trip_is_cleaned(self) -> None:
        # 删队列文件后、删照片目录前断电：下次启动时清掉已封存却没有队列文件的目录
        store = PointStore.create(self.spool, "rover-v2-old", {"field_id": 1, "device": "rover-v2",
                                                               "started_at": "2026-10-08T06:00:00+08:00"})
        store.seal("gone")
        unfinished = PointStore.create(self.spool, "rover-v2-new", {"field_id": 1, "device": "rover-v2",
                                                                    "started_at": "2026-10-08T07:00:00+08:00"})
        with _Platform() as platform:
            self.assertEqual(self._main(platform, "--flush-spool"), 0)
        self.assertFalse(store.directory.exists())
        self.assertFalse(unfinished.directory.exists())  # 一张没拍的中断巡检照旧删掉


class DefaultsTests(unittest.TestCase):
    def test_stops_is_the_default_mode_and_cucumber_the_default_crop(self) -> None:
        args = rover_run.parse_args([])
        self.assertEqual((args.mode, args.crop, args.stops, args.stop_spacing), ("stops", "cucumber", 5, 0.4))
        self.assertEqual(rover_run.parse_args(["--crop", "wheat"]).crop, "wheat")
        self.assertEqual(rover_run.CROPS["wheat"][0], "冬小麦")

    def test_layout_sets_stops_and_spacing(self) -> None:
        args = rover_run.parse_args(["--layout", LAYOUT, "--row", "2"])
        self.assertEqual((args.row_layout.row_no, args.stops, args.stop_spacing), (2, 30, 0.4))
        self.assertEqual(rover_run.parse_args(["--layout", LAYOUT, "--stops", "4"]).stops, 4)
        for bad in (["--row", "1"], ["--layout", LAYOUT, "--row", "9"], ["--layout", "/nonexistent.json"]):
            with self.subTest(args=bad), self.assertRaises(SystemExit), \
                    contextlib.redirect_stderr(io.StringIO()):
                rover_run.parse_args(bad)


if __name__ == "__main__":
    unittest.main()
