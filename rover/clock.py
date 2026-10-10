"""本机时钟状态（计划 0007 P0-2，决策 D26）：只检测和上报，不改系统时间。

Pi 3B 没有 RTC，断网开机时系统时间可能停在上次关机，甚至 1970 年。出车时记下两件事，随包（协议 v2 头部 ``clock``）上报：
- 系统报告的对时状态：先问 chrony（``chronyc -n tracking``），再问 systemd-timesyncd（``timedatectl``）；
- 与平台的时间差：联网时取 ``/api/v1/health`` 的 ``server_time``，按请求前后两次本机时间的中点算，正数表示本机快。
平台按时钟状态和各时间戳给出时间告警；用 DS3231 还是让 TX2 跑 chrony 做局域网时间源，由团队定。
"""
from __future__ import annotations

import subprocess
from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

# 与平台的告警阈值一致（backend services/clock_check.py），只用于车端当场提示
OFFSET_WARN_S = 60

# 跑一条命令，返回标准输出；命令不存在、超时或失败时返回 None
Runner = Callable[[list[str]], "str | None"]


def run_command(cmd: list[str]) -> str | None:
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=3, check=False)
    except (OSError, subprocess.SubprocessError):
        return None
    return result.stdout if result.returncode == 0 else None


def system_sync_state(run: Runner | None = None) -> tuple[bool | None, str]:
    """返回 (是否已对时, 来源)；查不到为 (None, "unknown")。"""
    run = run or run_command
    out = run(["chronyc", "-n", "tracking"])
    if out is not None:
        for line in out.splitlines():
            key, _, value = line.partition(":")
            if key.strip() == "Leap status":
                return value.strip() != "Not synchronised", "chrony"
        return None, "chrony"
    out = run(["timedatectl", "show", "-p", "NTPSynchronized", "--value"])
    if out is not None and out.strip() in ("yes", "no"):
        return out.strip() == "yes", "ntp"
    return None, "unknown"


def measure_offset(server_time: str | None, sent: datetime, received: datetime) -> float | None:
    """本机时间减平台时间（秒）。平台时间取请求往返的中点对齐；平台没给时间（旧版本）时返回 None。"""
    if not server_time:
        return None
    try:
        server = datetime.fromisoformat(server_time)
    except ValueError:
        return None
    if server.tzinfo is None:
        server = server.replace(tzinfo=timezone.utc)
    middle = sent + (received - sent) / 2
    return round((middle - server).total_seconds(), 3)


def clock_status(
    health: dict[str, Any] | None, sent: datetime | None, received: datetime | None, *, run: Runner | None = None,
) -> dict[str, Any]:
    """出车时的时钟状态（协议 v2 头部 ``clock``）；离线时 ``health`` 为 None，只有系统对时状态。"""
    synced, source = system_sync_state(run)
    offset = None
    if health is not None and sent is not None and received is not None:
        offset = measure_offset(health.get("server_time"), sent, received)
    return {
        "synced": synced,
        "source": source,
        "offset_s": offset,
        "measured_at": received.isoformat() if offset is not None and received is not None else None,
    }


def span(seconds: float) -> str:
    """把秒数写成「约 3 小时 5 分」这类说法，与平台 services/clock_check.py 的告警同口径。"""
    seconds = abs(seconds)
    if seconds < 90:
        return f"{seconds:.0f} 秒"
    minutes = round(seconds / 60)
    if minutes < 90:
        return f"约 {minutes} 分钟"
    hours, minutes = divmod(minutes, 60)
    if hours < 48:
        return f"约 {hours} 小时" + (f" {minutes} 分" if minutes else "")
    days = round(hours / 24)
    return f"约 {days} 天" if days < 730 else f"约 {round(days / 365.25)} 年"


def _gap(offset: float) -> str:
    return f"本机比平台{'快' if offset > 0 else '慢'} {span(offset)}"


def describe(status: dict[str, Any]) -> str:
    synced = {True: "已对时", False: "未对时", None: "对时状态未知"}[status.get("synced")]
    source = status.get("source", "unknown")
    text = synced if source == "unknown" else f"{synced}（{source}）"
    offset = status.get("offset_s")
    if offset is None:
        return f"{text}，离线没法和平台对表"
    if abs(offset) < 90:
        return f"{text}，与平台差 {round(offset, 1) + 0.0:+.1f} 秒"  # 加 0.0 免得显示成 -0.0
    return f"{text}，{_gap(offset)}"


def warning(status: dict[str, Any]) -> str | None:
    """车端当场提示；规则与平台一致：量到时间差就只看它，没量到再看系统对时状态。"""
    offset = status.get("offset_s")
    if offset is not None:
        if abs(offset) > OFFSET_WARN_S:
            return f"{_gap(offset)}，拍摄时间会不准：先对时再出车；照常拍的话平台会在巡检上标出"
        return None
    if status.get("synced") is False:
        return "系统报告时钟未对时，又没法和平台对表：拍摄时间可能不准，平台会在巡检上标出"
    return None
