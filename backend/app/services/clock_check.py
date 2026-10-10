"""采集端时间可信度检查（计划 0007 P0-2，决策 D26）：只告警，不改时间。

Pi 3B 没有 RTC，断网开机时系统时间可能停在上次关机，甚至 1970 年；拍摄时间错了，田间日期分组（D24）、
环境读数对齐和单株时间线都会跟着错。采集端上报本机时钟状态（是否已对时、联网时与平台的时间差），
平台在收包和收心跳时按下面的规则给出告警，存在巡检和心跳上，页面和车端都能看到。

规则（纯函数）：
- 时间戳晚于平台接收时间超过 ``FUTURE_TOLERANCE_S``：时钟快了；
- 时间戳早于 ``EARLIEST_PLAUSIBLE``：开机后没对时（停在默认时间）；
- 量到了与平台的时间差，且超过 ``OFFSET_WARN_S``：时钟不准；
- 没量到时间差（离线），且系统报告未对时：时间可能不准；
- 心跳没带时间差时，用心跳时间与平台接收时间之差代替（也可能是心跳延迟送达）。
"""
from __future__ import annotations

import math
from collections.abc import Iterable
from datetime import datetime, timezone
from typing import Any

from app.core.timeutil import to_utc

FUTURE_TOLERANCE_S = 300
OFFSET_WARN_S = 60
EARLIEST_PLAUSIBLE = datetime(2020, 1, 1, tzinfo=timezone.utc)


def _span(seconds: float) -> str:
    """把秒数写成「约 3 小时 5 分」这类说法。"""
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


def _warning(code: str, message: str) -> dict[str, str]:
    return {"code": code, "message": message}


def timestamp_warnings(
    stamps: Iterable[datetime], received_at: datetime, *, what: str = "拍摄时间",
) -> list[dict[str, str]]:
    """包里的时间（开始、结束、各点拍摄时间）或心跳时间与平台接收时间对比。"""
    stamps = [to_utc(stamp) for stamp in stamps]
    if not stamps:
        return []
    warnings = []
    latest = max(stamps)
    ahead = (latest - to_utc(received_at)).total_seconds()
    if ahead > FUTURE_TOLERANCE_S:
        warnings.append(_warning(
            "future_timestamp", f"{what}比平台接收时间还晚 {_span(ahead)}：车端时钟快了，{what}不可信",
        ))
    earliest = min(stamps)
    if earliest < EARLIEST_PLAUSIBLE:
        warnings.append(_warning(
            "implausible_timestamp",
            f"{what}早于 {EARLIEST_PLAUSIBLE.year} 年（{earliest:%Y-%m-%d}）：车端开机后没对时，{what}不可信",
        ))
    return warnings


def clock_warnings(clock: dict[str, Any] | None, *, skew_s: float | None = None) -> list[dict[str, str]]:
    """车端上报的时钟状态；``skew_s`` 是心跳时间减平台接收时间（只在没量到时间差时用）。"""
    clock = clock or {}
    offset = clock.get("offset_s")
    if offset is not None and math.isfinite(offset):
        if abs(offset) > OFFSET_WARN_S:
            direction = "快" if offset > 0 else "慢"
            return [_warning("clock_offset", f"车端时钟比平台{direction} {_span(offset)}：拍摄时间可能不准")]
        return []
    if clock.get("synced") is False:
        return [_warning("clock_unsynced", "车端系统报告时钟未对时，且没能和平台对表：拍摄时间可能不准")]
    if skew_s is not None and abs(skew_s) > OFFSET_WARN_S:
        direction = "晚" if skew_s > 0 else "早"
        return [_warning(
            "heartbeat_skew", f"心跳时间比平台接收时间{direction} {_span(skew_s)}：车端时钟不准，或心跳延迟送达",
        )]
    return []


def patrol_warnings(
    *, started_at: datetime, ended_at: datetime | None, captured: Iterable[datetime],
    clock: dict[str, Any] | None, received_at: datetime,
) -> list[dict[str, str]]:
    stamps = [started_at, *([ended_at] if ended_at else []), *captured]
    return timestamp_warnings(stamps, received_at) + clock_warnings(clock)


def heartbeat_warnings(
    *, observed_at: datetime | None, clock: dict[str, Any] | None, received_at: datetime,
) -> tuple[float | None, list[dict[str, str]]]:
    """返回 (心跳时间减接收时间的秒数, 告警)；心跳没带 observed_at（由平台补当前时间）时差值为空。"""
    skew = None if observed_at is None else round((to_utc(observed_at) - to_utc(received_at)).total_seconds(), 3)
    # 时钟快了由时间差规则报（心跳是实时发的），这里只补「早于 2020 年」
    stamps = [] if observed_at is None else [observed_at]
    stale = [w for w in timestamp_warnings(stamps, received_at, what="心跳时间") if w["code"] == "implausible_timestamp"]
    return skew, stale + clock_warnings(clock, skew_s=None if stale else skew)
