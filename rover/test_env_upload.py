"""温湿度记录仪 CSV 上传（计划 0015）：列名/时区可配、坏行处理、分批上传。只导入 rover 与标准库。

仓库根目录运行：``python -m unittest rover.test_env_upload``。
"""
from __future__ import annotations

import io
import tempfile
import unittest
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

from rover import env_upload
from rover.run import ApiError


class _FakeClient:
    """记录每次 POST，按平台语义返回 inserted / skipped（同一时刻只收一次）。"""

    instances: list["_FakeClient"] = []

    def __init__(self, base_url: str, **auth) -> None:
        self.base_url, self.auth = base_url, auth
        self.posts: list[tuple[str, dict]] = []
        self.seen: set[str] = set()
        self.fail_on_call: int | None = None
        _FakeClient.instances.append(self)

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def post(self, path, body, expect=(200, 201)):
        self.posts.append((path, body))
        if self.fail_on_call == len(self.posts):
            raise ApiError("HTTP 503", status_code=503, retryable=True)
        new = {r["observed_at"] for r in body["readings"]} - self.seen
        self.seen |= new
        return {"inserted": len(new), "skipped": len(body["readings"]) - len(new)}


def _write(text: str, encoding: str = "utf-8") -> Path:
    handle = tempfile.NamedTemporaryFile("w", suffix=".csv", delete=False, encoding=encoding)
    handle.write(text)
    handle.close()
    return Path(handle.name)


class ReadCsvTests(unittest.TestCase):
    def test_custom_columns_local_time_and_wetness(self) -> None:
        path = _write("时间,温度,湿度,叶湿\n2026/10/01 18:00:00,16.5,96%,0.7\n2026-10-01T18:30:00Z,16.0,97,\n")
        readings, errors = env_upload.read_csv(
            path, columns=env_upload.Columns("时间", "温度", "湿度", "叶湿"), tz=env_upload.parse_tz("+08:00"))
        self.assertEqual(errors, [])
        self.assertEqual(readings[0], {"observed_at": "2026-10-01T18:00:00+08:00", "temp_c": 16.5,
                                       "humidity_pct": 96.0, "leaf_wetness": 0.7})
        # 自带时区的时间保持原样，不再套参数时区；空的叶面湿度不上报
        self.assertEqual(readings[1], {"observed_at": "2026-10-01T18:30:00+00:00", "temp_c": 16.0,
                                       "humidity_pct": 97.0})

    def test_time_format_gbk_and_semicolon(self) -> None:
        path = _write("采集时间;温度℃;湿度%\n01-10-2026 06:00;12;99\n", encoding="gbk")
        readings, errors = env_upload.read_csv(
            path, columns=env_upload.Columns("采集时间", "温度℃", "湿度%"), tz=env_upload.parse_tz("UTC"),
            time_format="%d-%m-%Y %H:%M", encoding="gbk", delimiter=";")
        self.assertEqual(errors, [])
        self.assertEqual(readings[0]["observed_at"], "2026-10-01T06:00:00+00:00")

    def test_bad_rows_are_reported_with_line_numbers(self) -> None:
        path = _write("time,temp_c,humidity_pct\n2026-10-01T00:00:00,20,80\nnot-a-time,20,80\n2026-10-01T01:00:00,,80\n")
        readings, errors = env_upload.read_csv(path)
        self.assertEqual(len(readings), 1)
        self.assertEqual([e.split("：")[0] for e in errors], ["第 3 行", "第 4 行"])

    def test_missing_column_is_an_error(self) -> None:
        with self.assertRaises(ValueError):
            env_upload.read_csv(_write("when,t,h\n"), columns=env_upload.Columns())

    def test_parse_tz(self) -> None:
        self.assertEqual(env_upload.parse_tz("+0800"), timezone(timedelta(hours=8)))
        self.assertEqual(env_upload.parse_tz("-05:30"), timezone(-timedelta(hours=5, minutes=30)))
        with self.assertRaises(ValueError):
            env_upload.parse_tz("Asia/Shanghai")


class UploadTests(unittest.TestCase):
    def setUp(self) -> None:
        _FakeClient.instances.clear()
        start = datetime(2026, 10, 1, tzinfo=timezone.utc)
        rows = "\n".join(f"{(start + timedelta(minutes=10 * k)).isoformat()},18,90" for k in range(25))
        self.csv = _write("time,temp_c,humidity_pct\n" + rows + "\n")

    def _main(self, *extra: str) -> tuple[int, str]:
        out = io.StringIO()
        with redirect_stdout(out):
            code = env_upload.main(["--field-id", "7", "--csv", str(self.csv), "--sensor-key", "th-01",
                                    "--batch-size", "10", "--token", "t", *extra], client_factory=_FakeClient)
        return code, out.getvalue()

    def test_uploads_in_batches_and_reupload_is_skipped(self) -> None:
        code, out = self._main("--device", "gh-01")
        self.assertEqual(code, 0, out)
        client = _FakeClient.instances[-1]
        self.assertEqual([len(body["readings"]) for _, body in client.posts], [10, 10, 5])
        path, body = client.posts[0]
        self.assertEqual(path, "/api/v1/fields/7/env-readings")
        self.assertEqual((body["sensor_key"], body["source"], body["device"]), ("th-01", "import", "gh-01"))
        self.assertIn("新增 25", out)
        inserted, skipped = env_upload.upload(client, 7, "th-01", [r for _, b in client.posts for r in b["readings"]],
                                              batch_size=5000)
        self.assertEqual((inserted, skipped), (0, 25))

    def test_bad_rows_block_upload_unless_skip_bad(self) -> None:
        self.csv.write_text(self.csv.read_text() + "oops,1,2\n")
        code, out = self._main()
        self.assertEqual(code, 1)
        self.assertEqual(_FakeClient.instances, [])  # 一条都没发
        self.assertIn("--skip-bad", out)
        code, _ = self._main("--skip-bad")
        self.assertEqual(code, 0)

    def test_api_failure_returns_error(self) -> None:
        original = _FakeClient.__init__

        def failing(self, *args, **kwargs):
            original(self, *args, **kwargs)
            self.fail_on_call = 2

        _FakeClient.__init__ = failing  # type: ignore[method-assign]
        try:
            code, out = self._main()
        finally:
            _FakeClient.__init__ = original  # type: ignore[method-assign]
        self.assertEqual(code, 1)
        self.assertIn("上传失败", out)

    def test_batch_size_is_bounded(self) -> None:
        code, out = self._main("--batch-size", "5001")
        self.assertEqual(code, 2)
        self.assertIn("5000", out)


if __name__ == "__main__":
    unittest.main()
