"""无硬件烟测：验证 rover/run.py 的 HTTP 协议和失败清理边界。

本文件只导入 rover 入口和标准库/httpx 测试工具，不导入 backend 内部模块。
可从仓库根目录运行：``python -m unittest rover.test_run_smoke``。
"""
from __future__ import annotations

import base64
import json
import threading
import tempfile
import unittest
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from unittest.mock import patch
from urllib.parse import urlsplit

import httpx

from rover import run as rover_run
from simulator import client as simulator_client


class _RecordingHandler(BaseHTTPRequestHandler):
    """返回最小协议响应，并记录真实上传的巡检包。"""

    server: "_RecordingServer"

    def _send_json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_text(self, status: int, body: str) -> None:
        encoded = body.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(encoded)))
        self.end_headers()
        self.wfile.write(encoded)

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlsplit(self.path).path
        if path == "/api/v1/health":
            self._send_json(200, {"version": "smoke", "environment": "test", "database": "memory"})
        elif path == "/non-json":
            self._send_text(200, "upstream returned HTML")
        elif path in {"/api/v1/devices", "/api/v1/fields", "/api/v1/crops", "/api/v1/plantings"}:
            self._send_json(200, [])
        else:
            self._send_json(404, {"detail": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        length = int(self.headers.get("Content-Length", "0"))
        payload = json.loads(self.rfile.read(length))
        path = urlsplit(self.path).path
        self.server.posts.append((path, payload))
        if path == "/api/v1/devices":
            response = {"id": 11, "code": payload["code"], "name": payload["name"]}
        elif path == "/api/v1/fields":
            response = {"id": 22, "name": payload["name"]}
        elif path == "/api/v1/crops":
            response = {"id": 33, "name": payload["name"]}
        elif path == "/api/v1/plantings":
            response = {"id": 44, "crop_id": payload["crop_id"], "sowing_date": payload["sowing_date"]}
        elif path == "/api/v1/ingest/patrol":
            self.server.ingest_payload = payload
            response = {
                "patrol_id": 55,
                "capture_points": len(payload["capture_points"]),
                "photos_saved": len(payload["capture_points"]),
                "photos_referenced": 0,
            }
        else:
            self._send_json(404, {"detail": "not found"})
            return
        self._send_json(201, response)

    def log_message(self, *_args: object) -> None:
        return


class _RecordingServer(HTTPServer):
    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _RecordingHandler)
        self.posts: list[tuple[str, dict]] = []
        self.ingest_payload: dict | None = None
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)

    def __enter__(self) -> "_RecordingServer":
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.shutdown()
        self.server_close()
        self._thread.join(timeout=2)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}"


class _ProtocolHandler(BaseHTTPRequestHandler):
    """仅实现设备协议所需的最小 HTTP 合同，不导入后端。"""

    server: "_ProtocolServer"

    def _json(self, status: int, payload: object) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length)) if length else {}

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlsplit(self.path).path
        self.server.requests.append(("GET", path, None))
        if path.endswith("/tasks/next"):
            self._json(200, {
                "id": 700, "field_id": 1, "task_type": "revisit", "status": "queued",
                "priority": 0.9, "value_score": 0.8, "rationale": {"source": "smoke"},
                "parameters": {"seq": 3}, "created_by": "test",
            })
            return
        self._json(404, {"detail": "not found"})

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlsplit(self.path).path
        payload = self._read()
        self.server.requests.append(("POST", path, payload))
        if path == "/api/v1/devices/register":
            self._json(200, {
                "id": 21, "code": payload["code"], "name": payload["name"],
                "type": payload["type"], "status": payload.get("status", "idle"),
            })
        elif path.endswith("/heartbeat"):
            self._json(200, {"id": 301, "device_id": 21, **payload})
        elif path.endswith("/events"):
            self._json(201, {"id": 401, "device_id": 21, "mission_id": 55, **payload})
        else:
            self._json(404, {"detail": "not found"})

    def do_PATCH(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        path = urlsplit(self.path).path
        payload = self._read()
        self.server.requests.append(("PATCH", path, payload))
        if path == "/api/v1/revisit-tasks/700":
            self._json(200, {
                "id": 700, "field_id": 1, "task_type": "revisit", **payload,
            })
            return
        self._json(404, {"detail": "not found"})

    def log_message(self, *_args: object) -> None:
        return


class _ProtocolServer(HTTPServer):
    def __init__(self) -> None:
        super().__init__(("127.0.0.1", 0), _ProtocolHandler)
        self.requests: list[tuple[str, str, dict | None]] = []
        self._thread = threading.Thread(target=self.serve_forever, daemon=True)

    def __enter__(self) -> "_ProtocolServer":
        self._thread.start()
        return self

    def __exit__(self, *_args: object) -> None:
        self.shutdown()
        self.server_close()
        self._thread.join(timeout=2)

    @property
    def base_url(self) -> str:
        return f"http://127.0.0.1:{self.server_port}"


class _FailingCapture:
    instance: "_FailingCapture | None" = None

    def __init__(self, _width: int, _height: int) -> None:
        self.calls = 0
        self.closed = False
        type(self).instance = self

    def capture(self) -> bytes:
        self.calls += 1
        if self.calls == 2:
            raise RuntimeError("synthetic capture failure")
        return b"first-frame"

    def close(self) -> None:
        self.closed = True


class _FakeClient:
    instance: "_FakeClient | None" = None

    def __init__(self, _base_url: str) -> None:
        self.closed = False
        self.ingest_called = False
        type(self).instance = self

    def get(self, _path: str) -> dict:
        return {"version": "smoke", "environment": "test", "database": "memory"}

    def ensure_device(self, code: str, _name: str) -> dict:
        return {"id": 11, "code": code}

    def ensure_field(self, _name: str, _boundary: dict) -> dict:
        return {"id": 22}

    def ensure_crop(self, _name: str, _variety: str, _lifecycle_days: int, _stages: list[dict]) -> dict:
        return {"id": 33}

    def ensure_planting(self, _field_id: int, _crop_id: int, _sowing_date: str) -> dict:
        return {"id": 44}

    def ingest(self, _package: dict) -> dict:
        self.ingest_called = True
        raise AssertionError("capture failure must prevent upload")

    def close(self) -> None:
        self.closed = True


class _TransientUploadClient:
    def __init__(self) -> None:
        self.calls = 0

    def ingest(self, _package: dict) -> dict:
        self.calls += 1
        if self.calls < 3:
            raise rover_run.ApiError("temporary", retryable=True)
        return {
            "patrol_id": 55,
            "capture_points": 1,
            "photos_saved": 1,
            "photos_referenced": 0,
        }


class _OfflineUploadClient:
    def ingest(self, _package: dict) -> dict:
        raise rover_run.ApiError("offline", retryable=True)


class _InvalidUploadClient:
    def __init__(self) -> None:
        self.calls = 0

    def ingest(self, _package: dict) -> dict:
        self.calls += 1
        raise rover_run.ApiError("invalid package", status_code=422, retryable=False)


class RoverSmokeTests(unittest.TestCase):
    def test_fake_collection_posts_valid_timestamps_and_photos(self) -> None:
        with _RecordingServer() as server:
            result = rover_run.main([
                "--api", server.base_url,
                "--device", "smoke-rover",
                "--field-name", "smoke-field",
                "--points", "1",
                "--interval", "0",
                "--width", "32",
                "--height", "24",
                "--fake",
            ])

            self.assertEqual(result, 0)
            self.assertIsNotNone(server.ingest_payload)
            package = server.ingest_payload
            assert package is not None
            header = package["patrol"]
            started = datetime.fromisoformat(header["started_at"])
            ended = datetime.fromisoformat(header["ended_at"])
            self.assertLess(started, ended)

            points = package["capture_points"]
            self.assertEqual([point["seq"] for point in points], [0])
            captured = [datetime.fromisoformat(point["captured_at"]) for point in points]
            self.assertGreaterEqual(captured[0], started)
            self.assertLessEqual(captured[-1], ended)
            self.assertLessEqual(captured[0], captured[-1])
            for point in points:
                photo = base64.b64decode(point["photo"], validate=True)
                self.assertTrue(photo.startswith(b"\xff\xd8"), "fake photo must be JPEG")

    def test_non_json_response_is_a_runtime_error(self) -> None:
        with _RecordingServer() as server:
            client = rover_run.ApiClient(server.base_url)
            try:
                with self.assertRaisesRegex(RuntimeError, "非 JSON"):
                    client.get("/non-json")
            finally:
                client.close()

    def test_network_failure_is_a_runtime_error(self) -> None:
        client = rover_run.ApiClient("http://smoke.invalid")
        original = client._c
        original.close()

        def fail(request: httpx.Request) -> httpx.Response:
            raise httpx.ConnectError("synthetic network failure", request=request)

        client._c = httpx.Client(
            transport=httpx.MockTransport(fail),
            base_url=client.base_url,
        )
        try:
            with self.assertRaisesRegex(RuntimeError, "网络请求失败"):
                client.get("/api/v1/health")
        finally:
            client.close()

    def test_capture_failure_closes_source_and_client_without_upload(self) -> None:
        with patch.object(rover_run, "ApiClient", _FakeClient), patch.object(rover_run, "FakeCapture", _FailingCapture):
            result = rover_run.main([
                "--api", "http://smoke.invalid",
                "--fake",
                "--points", "2",
                "--interval", "0",
            ])

        self.assertEqual(result, 1)
        self.assertIsNotNone(_FailingCapture.instance)
        self.assertTrue(_FailingCapture.instance.closed)  # type: ignore[union-attr]
        self.assertIsNotNone(_FakeClient.instance)
        self.assertTrue(_FakeClient.instance.closed)  # type: ignore[union-attr]
        self.assertFalse(_FakeClient.instance.ingest_called)  # type: ignore[union-attr]

    def test_transient_upload_retries_without_changing_payload(self) -> None:
        client = _TransientUploadClient()
        package = {"patrol": {"device": "retry", "field_id": 1, "started_at": "t"}}
        result = rover_run.upload_with_retry(
            client, package, retries=2, sleeper=lambda _seconds: None,
        )
        self.assertEqual(result["patrol_id"], 55)
        self.assertEqual(client.calls, 3)

    def test_validation_error_is_not_retried(self) -> None:
        client = _InvalidUploadClient()
        package = {"patrol": {"device": "invalid", "field_id": 1, "started_at": "t"}}
        with self.assertRaisesRegex(RuntimeError, "invalid package"):
            rover_run.upload_with_retry(
                client, package, retries=3, sleeper=lambda _seconds: None,
            )
        self.assertEqual(client.calls, 1)

    def test_spool_replays_exact_package_and_removes_after_success(self) -> None:
        package = {
            "patrol": {
                "field_id": 1,
                "planting_id": 2,
                "device": "spool-rover",
                "started_at": "2026-09-19T08:00:00+08:00",
                "ended_at": "2026-09-19T08:00:01+08:00",
            },
            "capture_points": [{"seq": 0, "captured_at": "2026-09-19T08:00:00+08:00", "photo": "abc"}],
        }

        class Client:
            def __init__(self) -> None:
                self.payloads: list[dict] = []

            def ingest(self, payload: dict) -> dict:
                self.payloads.append(payload)
                return {"patrol_id": 99}

        with tempfile.TemporaryDirectory() as directory:
            spool = rover_run.PackageSpool(directory)
            queued = spool.save(package)
            client = Client()
            sent, failed = rover_run.flush_spool(
                client, spool, retries=0, sleeper=lambda _seconds: None,
            )
            self.assertEqual((sent, failed), (1, 0))
            self.assertFalse(queued.exists())
            self.assertEqual(client.payloads, [package])

    def test_offline_upload_keeps_spool_file_for_later_flush(self) -> None:
        package = {
            "patrol": {
                "field_id": 1,
                "device": "offline-rover",
                "started_at": "2026-09-19T08:00:00+08:00",
            },
            "capture_points": [],
        }
        with tempfile.TemporaryDirectory() as directory:
            spool = rover_run.PackageSpool(directory)
            queued = spool.save(package)
            sent, failed = rover_run.flush_spool(
                _OfflineUploadClient(), spool, retries=0, sleeper=lambda _seconds: None,
            )
            self.assertEqual((sent, failed), (0, 1))
            self.assertTrue(queued.exists())
            _, envelope = spool.read(queued)
            self.assertEqual(envelope["attempts"], 1)
            self.assertIn("offline", envelope["last_error"])

    def test_device_protocol_smoke_for_rover_and_simulator(self) -> None:
        """两个采集端适配器都只经 HTTP 完成注册→心跳→事件→领任务→状态回报。"""
        for make_client in (
            rover_run.ApiClient,
            simulator_client.ApiClient,
        ):
            with self.subTest(client=make_client.__module__), _ProtocolServer() as server:
                client = make_client(server.base_url)
                try:
                    device = client.register_device("smoke-protocol", "协议测试车")
                    self.assertEqual(device["id"], 21)

                    heartbeat = client.send_heartbeat(21, {
                        "client_heartbeat_id": "hb-smoke-1",
                        "status": "active",
                        "execution_phase": "ready",
                        "position_source": "unknown",
                        "queue_size": 0,
                        "payload": {"hardware": "fake"},
                    })
                    self.assertEqual(heartbeat["device_id"], 21)

                    event = client.report_event(21, {
                        "client_event_id": "evt-smoke-1",
                        "event_type": "self_check_passed",
                        "severity": "info",
                        "payload": {"camera": "ok"},
                    })
                    self.assertEqual(event["id"], 401)
                    mission_event = client.report_mission_event(55, {
                        "client_event_id": "evt-smoke-mission-1",
                        "event_type": "sample_persisted",
                        "severity": "info",
                        "payload": {"seq": 3},
                    })
                    self.assertEqual(mission_event["mission_id"], 55)

                    task = client.next_task(21)
                    self.assertIsNotNone(task)
                    assert task is not None
                    self.assertEqual(task["id"], 700)
                    for status in ("assigned", "running", "completed"):
                        updated = client.report_task_status(700, status, result_note=f"smoke:{status}")
                        self.assertEqual(updated["status"], status)
                finally:
                    client.close()

                paths = [(method, path) for method, path, _ in server.requests]
                self.assertIn(("POST", "/api/v1/devices/register"), paths)
                self.assertIn(("POST", "/api/v1/devices/21/heartbeat"), paths)
                self.assertIn(("POST", "/api/v1/devices/21/events"), paths)
                self.assertIn(("POST", "/api/v1/missions/55/events"), paths)
                self.assertIn(("GET", "/api/v1/devices/21/tasks/next"), paths)
                self.assertEqual(
                    [path for method, path in paths if method == "PATCH"],
                    ["/api/v1/revisit-tasks/700"] * 3,
                )


if __name__ == "__main__":
    unittest.main()
