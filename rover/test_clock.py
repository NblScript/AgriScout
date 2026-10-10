"""计划 0007 P0-2（决策 D26）：车端读系统对时状态、和平台量时间差，只上报不改时间。

仓库根目录运行 ``python -m unittest rover.test_clock``；不调用真实的 chronyc / timedatectl。
"""
from __future__ import annotations

import unittest
from datetime import datetime, timedelta, timezone

from rover import clock

CHRONY_OK = """Reference ID    : C0A80101 (192.168.1.1)
Stratum         : 3
System time     : 0.000012 seconds fast of NTP time
Leap status     : Normal
"""
CHRONY_UNSYNCED = CHRONY_OK.replace("Normal", "Not synchronised")
T0 = datetime(2026, 10, 10, 6, 0, tzinfo=timezone(timedelta(hours=8)))


def _runner(outputs: dict[str, str | None]):
    """按命令名返回预设输出；没列出的命令当作不存在。"""
    calls: list[list[str]] = []

    def run(cmd: list[str]) -> str | None:
        calls.append(cmd)
        return outputs.get(cmd[0])
    run.calls = calls  # type: ignore[attr-defined]
    return run


class SyncStateTests(unittest.TestCase):
    def test_chrony_is_asked_first(self) -> None:
        self.assertEqual(clock.system_sync_state(_runner({"chronyc": CHRONY_OK})), (True, "chrony"))
        self.assertEqual(clock.system_sync_state(_runner({"chronyc": CHRONY_UNSYNCED})), (False, "chrony"))
        self.assertEqual(clock.system_sync_state(_runner({"chronyc": "garbled"})), (None, "chrony"))

    def test_falls_back_to_timedatectl_then_unknown(self) -> None:
        run = _runner({"timedatectl": "yes\n"})
        self.assertEqual(clock.system_sync_state(run), (True, "ntp"))
        self.assertEqual([c[0] for c in run.calls], ["chronyc", "timedatectl"])
        self.assertEqual(clock.system_sync_state(_runner({"timedatectl": "no\n"})), (False, "ntp"))
        self.assertEqual(clock.system_sync_state(_runner({})), (None, "unknown"))

    def test_missing_command_does_not_raise(self) -> None:
        self.assertIsNone(clock.run_command(["agriscout-no-such-command"]))


class OffsetTests(unittest.TestCase):
    def test_offset_uses_the_middle_of_the_round_trip(self) -> None:
        server = (T0 + timedelta(seconds=1) - timedelta(seconds=30)).isoformat()  # 本机快 30 秒
        self.assertEqual(clock.measure_offset(server, T0, T0 + timedelta(seconds=2)), 30.0)
        self.assertEqual(clock.measure_offset("2026-10-09T22:00:00", T0, T0), 0.0)  # 无时区按 UTC
        self.assertIsNone(clock.measure_offset(None, T0, T0))  # 旧版平台不给 server_time
        self.assertIsNone(clock.measure_offset("not-a-time", T0, T0))

    def test_status_online_and_offline(self) -> None:
        run = _runner({"chronyc": CHRONY_OK})
        online = clock.clock_status({"server_time": T0.isoformat()}, T0, T0 + timedelta(seconds=0.2), run=run)
        self.assertEqual(online, {"synced": True, "source": "chrony", "offset_s": 0.1,
                                  "measured_at": (T0 + timedelta(seconds=0.2)).isoformat()})
        offline = clock.clock_status(None, None, None, run=_runner({"timedatectl": "no"}))
        self.assertEqual(offline, {"synced": False, "source": "ntp", "offset_s": None, "measured_at": None})

    def test_describe_and_warning_follow_platform_rules(self) -> None:
        good = {"synced": True, "source": "chrony", "offset_s": 0.4}
        self.assertEqual(clock.describe(good), "已对时（chrony），与平台差 +0.4 秒")
        self.assertEqual(clock.describe({"synced": None, "source": "unknown", "offset_s": -0.001}),
                         "对时状态未知，与平台差 +0.0 秒")
        self.assertIsNone(clock.warning(good))
        self.assertIsNone(clock.warning({"synced": False, "offset_s": 12.0}))  # 量到了且在阈值内
        self.assertIn("本机比平台慢 约 60 分钟", clock.warning({"synced": True, "offset_s": -3600.0}) or "")
        self.assertEqual(clock.describe({"synced": None, "source": "unknown", "offset_s": 10800.2}),
                         "对时状态未知，本机比平台快 约 3 小时")
        self.assertEqual(clock.span(-1_791_638_100), "约 57 年")
        offline = {"synced": False, "source": "unknown", "offset_s": None}
        self.assertEqual(clock.describe(offline), "未对时，离线没法和平台对表")
        self.assertIn("未对时", clock.warning(offline) or "")
        self.assertIsNone(clock.warning({"synced": None, "source": "unknown", "offset_s": None}))


if __name__ == "__main__":
    unittest.main()
