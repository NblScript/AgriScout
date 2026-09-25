"""时间约定（决策 D9）：库内一律存 UTC；按「天」计的农事语义用田间业务时区取日期。

背景：SQLite 存 DateTime 时直接丢弃时区、不做换算。采集端（rover/模拟器）上报东八区时间，
服务端默认值是 UTC，两种墙钟混存后无法比较（曾导致心跳乱序保护把新心跳全判为旧心跳）。
"""
from datetime import date, datetime, timedelta, timezone

UTC = timezone.utc
# 田间业务时区：生育期天数、按日统计等以田间本地日期为准。首批田块在国内，固定东八区；
# 将来多地区部署时改为地块属性。
FIELD_TZ = timezone(timedelta(hours=8))


def to_utc(value: datetime) -> datetime:
    """统一为带时区的 UTC 时间；无时区的输入按 UTC 解释（服务端默认值即 UTC）。"""
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def field_date(value: datetime) -> date:
    """时间点对应的田间本地日期（东八区凌晨的采集不会被算成前一天）。"""
    return to_utc(value).astimezone(FIELD_TZ).date()
