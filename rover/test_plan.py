"""计划 0016 阶段 C：下载巡检计划、按计划离线执行、上传后回报任务。

用本地 HTTP 假平台（按接口合同实现，不导入后端）；仓库根目录运行 ``python -m unittest rover.test_plan``。
"""
from __future__ import annotations

import contextlib
import io
import json
import socket
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from rover import acquire, hardware, plan, positioning
from rover import run as rover_run
from rover.point_store import PointStore
from rover.test_upload_v2 import LAYOUT, _Handler, _Platform, v2_violations

FIELD = 3
TZ = timezone(timedelta(hours=8))
RESHOOT_VIEWS = [
    {"name": "under-40", "side": "under", "pitch_deg": 40, "yaw_deg": 0, "height_m": 0.2, "fill_light": True},
    {"name": "under-60", "side": "under", "pitch_deg": 60, "yaw_deg": 0, "height_m": 0.2, "fill_light": True},
]
# 平台的任务状态机（对照 api/v1/software_loop.py 的 TASK_TRANSITIONS 按合同手写）
TRANSITIONS = {"queued": {"assigned", "cancelled"}, "assigned": {"running", "cancelled", "queued"},
               "running": {"completed", "cancelled"}, "completed": set(), "cancelled": set()}
LISTED = {"R01-P003", "R01-P010", "R01-P020", "R02-P001", "R02-P005", "pole-7"}


def _item(key: str, row: int | None, pos: int | None, list_name: str, task_id: int, status: str = "queued") -> dict:
    return {"unit_id": 100 + task_id, "key": key, "row_no": row, "position_no": pos, "list_name": list_name,
            "task_id": task_id, "task_type": plan.TASK_TYPES[list_name], "task_status": status, "score": 0.5,
            "priority": 0.5, "rationale": {}}


def _latest() -> dict:
    """平台 ``GET /fields/{id}/patrol-plans/latest`` 的返回：四张名单，一条任务已完成，一株是自定义键，一株不在布局里。"""
    return {
        "field_id": FIELD, "plan_version": "planner-v0", "plan_date": "2026-10-08", "generation": 4,
        "generated_at": "2026-10-07T22:00:00+00:00", "seed": "s", "units": 60, "reshoot_budget": 6, "env": {},
        "window": {"date": "2026-10-08", "start": "05:30", "end": "08:30", "night_of": "2026-10-07",
                   "night_wet_hours": 6, "reason": "前一夜湿润 6 小时"},
        "confirm": [_item("R01-P003", 1, 3, "confirm", 1)],
        "reshoot": [_item("R01-P010", 1, 10, "reshoot", 2)],
        "coverage": [_item("R02-P005", 2, 5, "coverage", 3), _item("R01-P020", 1, 20, "coverage", 4),
                     _item("R01-P001", 1, 1, "coverage", 6, status="completed"),
                     _item("pole-7", 2, 30, "coverage", 7)],
        "random": [_item("R02-P001", 2, 1, "random", 5), _item("R09-P001", 9, 1, "random", 8)],
        "params": None,
    }


def _tasks() -> dict[int, dict]:
    tasks = {}
    for name in plan.LISTS:
        for item in _latest()[name]:
            parameters = {"plan_version": "planner-v0", "list_name": name, "observation_key": item["key"]}
            if name == "reshoot":
                parameters["views"] = RESHOOT_VIEWS
            tasks[item["task_id"]] = {"id": item["task_id"], "field_id": FIELD, "task_type": item["task_type"],
                                      "status": item["task_status"], "parameters": parameters, "result_note": None}
    return tasks


class _PlanHandler(_Handler):
    def do_GET(self) -> None:  # noqa: N802
        url = urlsplit(self.path)
        platform = self.server
        if url.path == f"/api/v1/fields/{FIELD}/patrol-plans/latest":
            platform.log.append(("GET", url.path))
            if platform.plan is None:
                self._json(404, {"detail": "该地块还没有生成过巡检计划"})
            else:
                self._json(200, platform.plan)
        elif url.path == "/api/v1/revisit-tasks":
            platform.log.append(("GET", url.path))
            query = {key: values[0] for key, values in parse_qs(url.query).items()}
            rows = [task for task in platform.tasks.values()
                    if all(str(task[k]) == query[k] for k in ("field_id", "status", "task_type") if k in query)]
            self._json(200, rows[: int(query.get("limit", 100))])
        else:
            super().do_GET()

    def do_PATCH(self) -> None:  # noqa: N802
        path = urlsplit(self.path).path
        platform = self.server
        platform.log.append(("PATCH", path))
        task_id = int(path.rsplit("/", 1)[1])
        body = json.loads(self._body())
        platform.patches.append((task_id, body))
        task = platform.tasks.get(task_id)
        if task is None:
            self._json(404, {"detail": "复巡任务不存在"})
            return
        status = body.get("status")
        if task["status"] in {"completed", "cancelled"} and any(key != "status" for key in body):
            self._json(409, {"detail": "已结束的复巡任务不可修改"})
            return
        if status is not None and status != task["status"] and status not in TRANSITIONS[task["status"]]:
            self._json(422, {"detail": f"任务状态不能从 {task['status']} 转为 {status}"})
            return
        task.update(body)
        self._json(200, task)


def _plan_platform() -> _Platform:
    platform = _Platform(_PlanHandler)
    platform.plan = _latest()
    platform.tasks = _tasks()
    platform.patches = []
    return platform


def _closed_port_url() -> str:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    return f"http://127.0.0.1:{port}"


class PlanEndToEndTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.spool = self.root / "spool"
        self.plan_path = self.root / "plan.json"

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _main(self, api: str, *extra: str) -> tuple[int, str]:
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = rover_run.main([
                "--api", api, "--fake", "--interval", "0", "--width", "64", "--height", "48",
                "--device", "rover-plan", "--spool-dir", str(self.spool), "--upload-retries", "0", *extra,
            ])
        return code, out.getvalue()

    def _fetch(self, platform: _Platform) -> dict:
        code, out = self._main(platform.base_url, "--plan-fetch", str(self.plan_path), "--field-id", str(FIELD))
        self.assertEqual(code, 0, out)
        return json.loads(self.plan_path.read_text(encoding="utf-8"))

    def test_fetch_saves_stops_in_driving_order_with_task_views(self) -> None:
        with _plan_platform() as platform:
            data = self._fetch(platform)
        self.assertEqual(data["format"], plan.PLAN_FORMAT)
        self.assertEqual((data["field_id"], data["plan_date"], data["generation"]), (FIELD, "2026-10-08", 4))
        self.assertEqual([s["key"] for s in data["stops"]],
                         ["R01-P003", "R01-P010", "R01-P020", "R02-P001", "R02-P005", "pole-7", "R09-P001"])
        reshoot = next(s for s in data["stops"] if s["list_name"] == "reshoot")
        self.assertEqual([(v["side"], v["pitch_deg"]) for v in reshoot["views"]], [("under", 40), ("under", 60)])
        self.assertTrue(all(s["views"] is None for s in data["stops"] if s["list_name"] != "reshoot"))
        self.assertEqual([s["task_id"] for s in data["skipped"]], [6])  # 已完成的任务不再去拍
        self.assertEqual(data["warnings"], [])
        self.assertEqual(platform.records["/api/v1/devices"][0]["code"], "rover-plan")  # 顺带登记这台车

    def test_fetch_without_a_plan_fails_clearly(self) -> None:
        with _plan_platform() as platform:
            platform.plan = None
            code, out = self._main(platform.base_url, "--plan-fetch", str(self.plan_path), "--field-id", str(FIELD))
        self.assertEqual(code, 1)
        self.assertIn("巡检计划", out)
        self.assertFalse(self.plan_path.exists())

    def test_reshoot_task_without_views_falls_back_with_a_warning(self) -> None:
        with _plan_platform() as platform:
            platform.tasks[2]["parameters"].pop("views")
            data = self._fetch(platform)
        self.assertIsNone(next(s for s in data["stops"] if s["list_name"] == "reshoot")["views"])
        self.assertEqual(len(data["warnings"]), 1)

    def test_offline_run_shoots_only_listed_plants_then_flush_reports_tasks(self) -> None:
        with _plan_platform() as platform:
            self._fetch(platform)
        # 棚里没网：照常拍完，包和任务结果留在队列
        code, out = self._main(_closed_port_url(), "--plan", str(self.plan_path), "--layout", LAYOUT)
        self.assertEqual(code, 0, out)
        self.assertIn("[离线]", out)
        [queued] = sorted(self.spool.glob("*.json"))
        envelope = json.loads(queued.read_text(encoding="utf-8"))
        points = envelope["package"]["capture_points"]
        # 只拍了名单里的株（布局里找不到的 R09-P001 不停车）；自定义键的株用平台上的键
        self.assertEqual({p["observation_key"] for p in points}, LISTED)
        by_key: dict[str, list[dict]] = {}
        for point in points:
            by_key.setdefault(point["observation_key"], []).append(point)
        # 补拍株用任务指定的两个叶背视角，其余按三个标准视角
        self.assertEqual([(p["view"]["side"], p["view"]["pitch_deg"]) for p in by_key["R01-P010"]],
                         [("under", 40), ("under", 60)])
        for key in LISTED - {"R01-P010"}:
            self.assertEqual([p["view"]["side"] for p in by_key[key]], ["upper", "under", "under"], key)
        self.assertEqual(by_key["R02-P005"][0]["route_chainage_m"], 2.1)  # 0.5 + 4 × 0.4
        self.assertNotEqual(by_key["R02-P005"][0]["lng"], by_key["R01-P010"][0]["lng"])  # 跨垄经度错开示意
        self.assertEqual({p["position_source"] for p in points}, {"tag"})
        self.assertEqual(envelope["package"]["patrol"]["field_id"], FIELD)
        reports = {item["key"]: item for item in envelope["task_reports"]["items"]}
        self.assertEqual({key for key, item in reports.items() if item["done"]}, LISTED)
        self.assertIn("布局里找不到", reports["R09-P001"]["detail"])

        with _plan_platform() as platform:
            code, out = self._main(platform.base_url, "--flush-spool")
            self.assertEqual(code, 0, out)
            self.assertEqual(v2_violations(platform.ingested[0]), [])
            tasks = platform.tasks
            patches = platform.patches
        self.assertEqual(list(self.spool.glob("*.json")), [])
        self.assertEqual(list(self.spool.iterdir()), [])  # 照片目录也删了
        for task_id in (2, 3, 4, 5, 7):
            self.assertEqual(tasks[task_id]["status"], "completed", task_id)
            self.assertIn("已拍", tasks[task_id]["result_note"])
            self.assertIn("巡检 #100", tasks[task_id]["result_note"])
        self.assertEqual([body for task_id, body in patches if task_id == 3][1:3],
                         [{"status": "assigned"}, {"status": "running"}])
        # 没拍成的只写原因、状态不动；确认任务由人关闭，车不碰；已完成的不碰
        self.assertEqual(tasks[8]["status"], "queued")
        self.assertIn("未完成", tasks[8]["result_note"])
        self.assertEqual((tasks[1]["status"], tasks[1]["result_note"]), ("queued", None))
        self.assertNotIn(1, {task_id for task_id, _ in patches})
        self.assertNotIn(6, {task_id for task_id, _ in patches})

    def test_online_run_uploads_and_reports_at_once(self) -> None:
        with _plan_platform() as platform:
            self._fetch(platform)
            platform.tasks[4]["status"] = "cancelled"  # 下载之后被新一版计划作废
            code, out = self._main(platform.base_url, "--plan", str(self.plan_path), "--layout", LAYOUT)
            tasks = platform.tasks
        self.assertEqual(code, 0, out)
        self.assertEqual(tasks[3]["status"], "completed")
        self.assertEqual((tasks[4]["status"], tasks[4]["result_note"]), ("cancelled", None))
        self.assertIn("跳过 1 条", out)
        self.assertEqual(list(self.spool.iterdir()), [])

    def test_task_report_interrupted_by_network_is_finished_on_next_flush(self) -> None:
        with _plan_platform() as platform:
            self._fetch(platform)
        self.assertEqual(self._main(_closed_port_url(), "--plan", str(self.plan_path), "--layout", LAYOUT)[0], 0)
        with _plan_platform() as platform:
            platform.tasks[5]["status"] = "assigned"  # 回报到一半断网：这条已走到 assigned
            self.assertEqual(self._main(platform.base_url, "--flush-spool")[0], 0)
            self.assertEqual(platform.tasks[5]["status"], "completed")
            self.assertEqual([body.get("status") for task_id, body in platform.patches if task_id == 5],
                             [None, "running", "completed"])


class RunPlanTests(unittest.TestCase):
    def setUp(self) -> None:
        self._tmp = tempfile.TemporaryDirectory()
        self.rows = plan.rows_by_no(positioning.load_layout(LAYOUT))
        self.views = acquire.load_views(Path(rover_run.__file__).with_name("views.example.json"))

    def tearDown(self) -> None:
        self._tmp.cleanup()

    def _stops(self, *items: dict) -> list[dict]:
        return [{"key": i["key"], "row_no": i["row_no"], "position_no": i["position_no"], "list_name": i["list_name"],
                 "task_id": i["task_id"], "task_type": i["task_type"],
                 "views": RESHOOT_VIEWS if i["list_name"] == "reshoot" else None} for i in items]

    def _run(self, stops: list[dict], *, camera: hardware.FakeCamera, drive=None,
             store: PointStore | None = None) -> PointStore:
        store = store or PointStore.create(self._tmp.name, "trip", {
            "field_id": FIELD, "device": "t", "started_at": "2026-10-08T06:00:00+08:00"})
        drive = drive or hardware.FakeDrive()

        def tag_here() -> str | None:
            row = self.rows.get(drive.row_no)
            plant_no = row.plant_at(drive.position_m) if row else None
            return positioning.plant_key(row.row_no, plant_no) if plant_no else None

        rig = acquire.Rig(camera, hardware.FakeGimbal(), hardware.FakeLight(),
                          hardware.FakeTagReader([], source=tag_here))
        clock = iter(datetime(2026, 10, 8, 6, 0, tzinfo=TZ) + timedelta(seconds=n) for n in range(10_000))
        plan.run_plan(store, rig, stops, drive=drive, odometer=drive, rows=self.rows, standard_views=self.views,
                      policy=acquire.ShootPolicy(), clock=lambda: next(clock), base_lng=116.1, base_lat=39.1,
                      log=lambda _msg: None)
        return store

    def test_reshoot_that_never_passes_quality_is_not_done(self) -> None:
        stops = self._stops(_item("R01-P010", 1, 10, "reshoot", 2))
        store = self._run(stops, camera=hardware.FakeCamera(64, 48, ["blurry"] * 6))
        self.assertEqual(len(store.points), 6)  # 两个叶背视角各拍满 3 次
        [report] = plan.task_reports(store.points, {"plan_date": "2026-10-08", "stops": stops}, self.rows)["items"]
        self.assertFalse(report["done"])
        self.assertIn("叶背拍了 6 次都不合格", report["detail"])

    def test_stopping_at_the_wrong_plant_is_caught_by_the_tag(self) -> None:
        class ShortDrive(hardware.FakeDrive):
            def go_to(self, row_no: int, chainage_m: float) -> None:
                super().go_to(row_no, chainage_m - 0.4)  # 停早了一株

        stops = self._stops(_item("R01-P010", 1, 10, "coverage", 3))
        store = self._run(stops, camera=hardware.FakeCamera(64, 48), drive=ShortDrive())
        self.assertEqual({p["observation_key"] for p in store.points}, {"R01-P009"})
        [report] = plan.task_reports(store.points, {"plan_date": "2026-10-08", "stops": stops}, self.rows)["items"]
        self.assertFalse(report["done"])
        self.assertIn("不是计划株 R01-P010", report["detail"])

    def test_resume_skips_finished_plants_and_unvisited_ones_count_as_interrupted(self) -> None:
        stops = self._stops(_item("R01-P003", 1, 3, "random", 5), _item("R01-P010", 1, 10, "reshoot", 2),
                            _item("R02-P005", 2, 5, "coverage", 3))

        class PowerCut(BaseException):
            pass

        class DyingCamera(hardware.FakeCamera):
            def capture(self) -> bytes:
                if self.calls == 4:  # 第 2 株的第一个叶背视角拍完后断电
                    raise PowerCut
                return super().capture()

        with self.assertRaises(PowerCut):
            self._run(stops, camera=DyingCamera(64, 48))
        partial = PointStore(Path(self._tmp.name) / "trip")
        partial.resume()
        self.assertEqual([p["stop"] for p in partial.points], [0, 0, 0, 1])
        reports = plan.task_reports(partial.points, {"plan_date": "2026-10-08", "stops": stops}, self.rows)["items"]
        self.assertEqual([r["done"] for r in reports], [True, True, False])
        self.assertIn("中断", reports[2]["detail"])

        drive = hardware.FakeDrive()
        store = self._run(stops, camera=hardware.FakeCamera(64, 48), drive=drive, store=partial)
        self.assertEqual(drive.visits, [(1, 4.1), (2, 2.1)])  # 第 1 株已拍完，不再过去
        self.assertEqual([p["stop"] for p in store.points], [0, 0, 0, 1, 1, 2, 2, 2])
        self.assertEqual([p["view"]["pitch_deg"] for p in store.points if p["stop"] == 1], [40, 60])


class _FakeTaskClient:
    def __init__(self, statuses: dict[int, str], *, offline_after: int | None = None) -> None:
        self.statuses = statuses
        self.calls: list[tuple] = []
        self.offline_after = offline_after

    def _count(self) -> None:
        if self.offline_after is not None and len(self.calls) > self.offline_after:
            raise rover_run.ApiError("网络请求失败", retryable=True)

    def note_task(self, task_id: int, note: str) -> dict:
        self.calls.append(("note", task_id))
        self._count()
        if self.statuses[task_id] in {"completed", "cancelled"}:
            raise rover_run.ApiError("HTTP 409", status_code=409)
        return {"id": task_id, "status": self.statuses[task_id]}

    def report_task_status(self, task_id: int, status: str, *, result_note: str | None = None) -> dict:
        self.calls.append((status, task_id))
        self._count()
        self.statuses[task_id] = status
        return {"id": task_id, "status": status}


class ReportTasksTests(unittest.TestCase):
    REPORTS = {"plan_date": "2026-10-08", "generation": 4, "items": [
        {"task_id": 1, "list_name": "confirm", "key": "a", "done": True, "detail": "x"},
        {"task_id": 2, "list_name": "reshoot", "key": "b", "done": True, "detail": "x"},
        {"task_id": 3, "list_name": "coverage", "key": "c", "done": False, "detail": "x"},
        {"task_id": 4, "list_name": "random", "key": "d", "done": True, "detail": "x"},
        {"task_id": 5, "list_name": "coverage", "key": "e", "done": True, "detail": "x"},
    ]}

    def test_walks_the_state_machine_from_the_current_status(self) -> None:
        client = _FakeTaskClient({1: "queued", 2: "queued", 3: "queued", 4: "running", 5: "cancelled"})
        counts = plan.report_tasks(client, self.REPORTS, patrol_id=9, log=lambda _msg: None)
        self.assertEqual(counts, {"completed": 2, "noted": 1, "skipped": 1})
        self.assertEqual(client.calls, [
            ("note", 2), ("assigned", 2), ("running", 2), ("completed", 2),
            ("note", 3),
            ("note", 4), ("completed", 4),
            ("note", 5),
        ])
        self.assertEqual(client.statuses, {1: "queued", 2: "completed", 3: "queued", 4: "completed", 5: "cancelled"})

    def test_network_error_propagates_so_the_package_stays_queued(self) -> None:
        client = _FakeTaskClient({1: "queued", 2: "queued", 3: "queued", 4: "queued", 5: "queued"}, offline_after=2)
        with self.assertRaises(rover_run.ApiError):
            plan.report_tasks(client, self.REPORTS, patrol_id=9, log=lambda _msg: None)


class PlanFileTests(unittest.TestCase):
    def test_window_warnings_only_warn(self) -> None:
        data = {"plan_date": "2026-10-08", "window": _latest()["window"]}
        self.assertEqual(plan.window_warnings(data, datetime(2026, 10, 8, 6, 0, tzinfo=TZ)), [])
        [late] = plan.window_warnings(data, datetime(2026, 10, 8, 9, 0, tzinfo=TZ))
        self.assertIn("不在窗口内", late)
        self.assertEqual(len(plan.window_warnings(data, datetime(2026, 10, 9, 6, 0, tzinfo=TZ))), 2)
        self.assertEqual(plan.window_warnings({"plan_date": "2026-10-08", "window": None},
                                              datetime(2026, 10, 8, 14, 0, tzinfo=TZ)), [])

    def test_parse_plan_rejects_bad_files(self) -> None:
        good = {"format": plan.PLAN_FORMAT, "field_id": 3, "plan_date": "2026-10-08",
                "stops": [{"key": "R01-P001", "row_no": 1, "position_no": 1, "list_name": "coverage", "task_id": 1}]}
        self.assertIs(plan.parse_plan(good), good)
        for bad in ({**good, "format": "x"}, {**good, "field_id": 0}, {**good, "plan_date": "tomorrow"},
                    {**good, "stops": [{**good["stops"][0], "key": "bad key"}]},
                    {**good, "stops": [{**good["stops"][0], "list_name": "other"}]},
                    {**good, "stops": [{**good["stops"][0], "views": [{"side": "left", "pitch_deg": 0}]}]}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                plan.parse_plan(bad)

    def test_argument_rules(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = plan.save_plan(Path(tmp) / "plan.json", {
                "format": plan.PLAN_FORMAT, "field_id": 3, "plan_date": "2026-10-08", "stops": []})
            args = rover_run.parse_args(["--plan", str(path), "--layout", LAYOUT])
            self.assertEqual((args.plan_data["field_id"], len(args.layout_rows)), (3, 2))
            for bad in (["--plan", str(path)], ["--plan", str(path), "--layout", LAYOUT, "--row", "1"],
                        ["--plan", str(path), "--layout", LAYOUT, "--stops", "3"],
                        ["--plan", str(path), "--layout", LAYOUT, "--mode", "legacy"],
                        ["--plan", str(path), "--layout", LAYOUT, "--field-id", "4"],
                        ["--plan", str(Path(tmp) / "missing.json"), "--layout", LAYOUT],
                        ["--plan-fetch", str(path)],
                        ["--plan-fetch", str(Path(tmp) / "spool" / "plan.json"), "--field-id", "3",
                         "--spool-dir", str(Path(tmp) / "spool")],
                        ["--plan-fetch", str(path), "--field-id", "3", "--plan", str(path)]):
                with self.subTest(args=bad), self.assertRaises(SystemExit), \
                        contextlib.redirect_stderr(io.StringIO()):
                    rover_run.parse_args(bad)


if __name__ == "__main__":
    unittest.main()
