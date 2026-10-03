"""棚内环境 → 黄瓜霜霉病环境指标（计划 0015，纯函数，不读写数据库）。

输入是温湿度记录仪的逐条读数，输出三层结果：
- 小时聚合：温度、湿度均值，最小露点差，叶面湿度最大值，读数条数。缺测的小时只标记，不插值。
- 逐日指标（按田间日期 ``field_date``）：适宜时长、湿润时长、夜间湿润时长、日温差、覆盖率。
- 环境指数 ``env_index``：近 72 小时适宜与湿润时长的饱和函数。覆盖率不足时为 None，**不得当成低风险**。

全部阈值集中在 :class:`DownyMildewEnvParams`，都是经验初值，待农技复核；这是启发式规则，不是训练出来的模型。
"""
from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass
from datetime import date, datetime, timedelta
from typing import Any

from app.core.timeutil import FIELD_TZ, field_date, to_utc

METHOD = "dm-env-v0"

# Magnus 公式系数（水面饱和水汽压，-45~60℃ 适用；Alduchov & Eskridge 1996 的常用取值）
MAGNUS_A = 17.62
MAGNUS_B = 243.12


@dataclass(frozen=True)
class DownyMildewEnvParams:
    """霜霉病环境判据。出处见计划 0013「依据」；全部待农技复核。"""

    # 适宜发病：15–25℃ 且相对湿度 85% 以上（0013 场景约束；中国发展门户网《黄瓜霜霉病的发病症状及防治措施》、
    # APS《Diagnostic Guide for Cucurbit Downy Mildew》）
    favorable_temp_min: float = 15.0
    favorable_temp_max: float = 25.0
    favorable_rh_min: float = 85.0
    # 湿润（叶面可能有水膜，孢子囊萌发与侵染需要）：近饱和湿度、露点差很小或叶面湿度传感器读数过半。
    # 95% 与 1.0℃ 是结露的经验近似判据，0.5 是把叶面湿度传感器读数归一到 0–1 后的中值，都待传感器标定与农技复核
    wet_rh_min: float = 95.0
    wet_dewpoint_depression_max: float = 1.0
    wet_leaf_wetness_min: float = 0.5
    # 夜间：当地 18:00 到次日 08:00（塑料大棚夜间降温结露，0013 场景约束）
    night_start_hour: int = 18
    night_end_hour: int = 8
    # 近 72 小时的环境指数：1 − exp(−(适宜时长 + 湿润时长) / 24)；平均覆盖率低于 0.5 时不给指数
    index_window_hours: int = 72
    index_scale_hours: float = 24.0
    min_coverage: float = 0.5
    # 清晨窗口：前一夜湿润 ≥ 4 小时，建议次日当地 05:30–08:30 拍叶背（0013 背景：部分征兆只在清晨高湿时明显；
    # 时长与时段都是经验值，待试拍校准）
    morning_trigger_night_wet_hours: int = 4
    morning_window_start: str = "05:30"
    morning_window_end: str = "08:30"


DEFAULT_PARAMS = DownyMildewEnvParams()


@dataclass(frozen=True)
class Reading:
    observed_at: datetime
    temp_c: float
    humidity_pct: float
    leaf_wetness: float | None = None


def dew_point(temp_c: float, humidity_pct: float) -> float | None:
    """Magnus 公式露点（℃）；湿度不为正时无定义，返回 None。"""
    if humidity_pct <= 0:
        return None
    gamma = math.log(min(humidity_pct, 100.0) / 100.0) + MAGNUS_A * temp_c / (MAGNUS_B + temp_c)
    return MAGNUS_B * gamma / (MAGNUS_A - gamma)


def _hour_floor(value: datetime) -> datetime:
    return to_utc(value).replace(minute=0, second=0, microsecond=0)


def hourly(readings: Iterable[Reading], start: datetime, end: datetime) -> list[dict[str, Any]]:
    """[start, end) 内逐小时聚合（UTC 整点，东八区与 UTC 整点对齐）；没有读数的小时 ``missing=True``、数值为空。"""
    buckets: dict[datetime, list[Reading]] = {}
    for reading in readings:
        buckets.setdefault(_hour_floor(reading.observed_at), []).append(reading)
    hours: list[dict[str, Any]] = []
    hour = _hour_floor(start)
    end = to_utc(end)
    while hour < end:
        rows = buckets.get(hour, [])
        if rows:
            depressions = [
                r.temp_c - td for r in rows if (td := dew_point(r.temp_c, r.humidity_pct)) is not None
            ]
            wetness = [r.leaf_wetness for r in rows if r.leaf_wetness is not None]
            hours.append({
                "hour": hour, "count": len(rows), "missing": False,
                "temp_c": sum(r.temp_c for r in rows) / len(rows),
                "humidity_pct": sum(r.humidity_pct for r in rows) / len(rows),
                "dewpoint_depression_min": min(depressions) if depressions else None,
                "leaf_wetness_max": max(wetness) if wetness else None,
            })
        else:
            hours.append({"hour": hour, "count": 0, "missing": True, "temp_c": None, "humidity_pct": None,
                          "dewpoint_depression_min": None, "leaf_wetness_max": None})
        hour += timedelta(hours=1)
    return hours


def is_favorable(hour: dict[str, Any], params: DownyMildewEnvParams = DEFAULT_PARAMS) -> bool:
    if hour["missing"]:
        return False
    return (params.favorable_temp_min <= hour["temp_c"] <= params.favorable_temp_max
            and hour["humidity_pct"] >= params.favorable_rh_min)


def is_wet(hour: dict[str, Any], params: DownyMildewEnvParams = DEFAULT_PARAMS) -> bool:
    if hour["missing"]:
        return False
    depression = hour["dewpoint_depression_min"]
    wetness = hour["leaf_wetness_max"]
    return (hour["humidity_pct"] >= params.wet_rh_min
            or (depression is not None and depression <= params.wet_dewpoint_depression_max)
            or (wetness is not None and wetness >= params.wet_leaf_wetness_min))


def _local_hour(hour: dict[str, Any]) -> int:
    return hour["hour"].astimezone(FIELD_TZ).hour


def _night_of(hour: dict[str, Any], params: DownyMildewEnvParams) -> date | None:
    """夜晚归到傍晚那天：D 日 18:00 到 D+1 日 08:00 都算「D 日的夜晚」；白天返回 None。"""
    local = hour["hour"].astimezone(FIELD_TZ)
    if local.hour >= params.night_start_hour:
        return local.date()
    if local.hour < params.night_end_hour:
        return local.date() - timedelta(days=1)
    return None


def daily(hours: Sequence[dict[str, Any]], params: DownyMildewEnvParams = DEFAULT_PARAMS) -> list[dict[str, Any]]:
    """按田间日期的逐日指标。

    ``night_wet_hours`` / ``night_coverage`` 说的是当天傍晚开始的那一夜（到次日 08:00），不是当天凌晨。
    """
    by_day: dict[date, list[dict[str, Any]]] = {}
    nights: dict[date, list[dict[str, Any]]] = {}
    for hour in hours:
        by_day.setdefault(field_date(hour["hour"]), []).append(hour)
        night = _night_of(hour, params)
        if night is not None:
            nights.setdefault(night, []).append(hour)
    night_hours = (24 - params.night_start_hour) + params.night_end_hour
    output = []
    for day in sorted(by_day):
        rows = [h for h in by_day[day] if not h["missing"]]
        temps = [h["temp_c"] for h in rows]
        output.append({
            "field_date": day,
            "favorable_hours": sum(1 for h in rows if is_favorable(h, params)),
            "wet_hours": sum(1 for h in rows if is_wet(h, params)),
            "night_wet_hours": sum(1 for h in nights.get(day, []) if is_wet(h, params)),
            "night_coverage": round(sum(1 for h in nights.get(day, []) if not h["missing"]) / night_hours, 4),
            "diurnal_range": round(max(temps) - min(temps), 2) if temps else None,
            "coverage": round(len(rows) / 24, 4),
        })
    return output


def env_index(
    hours: Sequence[dict[str, Any]], as_of: datetime, params: DownyMildewEnvParams = DEFAULT_PARAMS,
) -> dict[str, Any]:
    """as_of 之前 72 小时的环境指数与分量；覆盖率不足时 ``env_index`` 为 None（无环境信息，不是低风险）。"""
    end = _hour_floor(as_of)
    start = end - timedelta(hours=params.index_window_hours)
    window = [h for h in hours if start <= h["hour"] < end]
    valid = [h for h in window if not h["missing"]]
    favorable = sum(1 for h in valid if is_favorable(h, params))
    wet = sum(1 for h in valid if is_wet(h, params))
    coverage = len(valid) / params.index_window_hours
    index = None
    if coverage >= params.min_coverage:
        index = round(1.0 - math.exp(-(favorable + wet) / params.index_scale_hours), 4)
    return {
        "method": METHOD, "env_index": index, "as_of": end, "window_hours": params.index_window_hours,
        "favorable_hours": favorable, "wet_hours": wet, "coverage": round(coverage, 4),
        "reason": None if index is not None else f"近 {params.index_window_hours} 小时覆盖率 {coverage:.0%}，低于 {params.min_coverage:.0%}，按无环境信息处理",
    }


def morning_window(
    days: Sequence[dict[str, Any]], plan_date: date, params: DownyMildewEnvParams = DEFAULT_PARAMS,
) -> dict[str, Any] | None:
    """计划日前一夜湿润够久时，建议计划日清晨拍叶背。

    「前一夜」是计划日前一天傍晚到计划日 08:00；计划时这一夜还没有数据（例如前一天傍晚就排计划），
    改看再前一夜。两夜都没有数据就不给建议。
    """
    by_day = {d["field_date"]: d for d in days}
    for offset in (1, 2):
        night = by_day.get(plan_date - timedelta(days=offset))
        if night is None or night["night_coverage"] == 0:
            continue
        wet = night["night_wet_hours"]
        if wet >= params.morning_trigger_night_wet_hours:
            return {
                "date": plan_date, "start": params.morning_window_start, "end": params.morning_window_end,
                "night_of": night["field_date"], "night_wet_hours": wet,
                "reason": f"{night['field_date']} 夜间湿润 {wet} 小时（≥{params.morning_trigger_night_wet_hours}），清晨叶背征兆更明显",
            }
        return None
    return None


def summarize(
    readings: Sequence[Reading], as_of: datetime, plan_date: date | None = None,
    params: DownyMildewEnvParams = DEFAULT_PARAMS, history_days: int = 7,
) -> dict[str, Any]:
    """计划和接口共用的环境摘要：as_of 前 history_days 天的小时序列、逐日指标、环境指数和清晨窗口。"""
    end = _hour_floor(as_of)
    if to_utc(as_of) > end:  # 把 as_of 所在的不完整小时也画出来
        end += timedelta(hours=1)
    start = end - timedelta(days=history_days)
    hours = hourly(readings, start, end)
    days = daily(hours, params)
    index = env_index(hours, as_of, params)
    window = morning_window(days, plan_date or field_date(as_of), params)
    return {"params": asdict(params), "hourly": hours, "daily": days, "index": index, "morning_window": window}
