"""计划 0015：霜霉病环境指标（纯函数）。"""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.core.timeutil import FIELD_TZ
from app.services.greenhouse_env import (
    Reading,
    daily,
    dew_point,
    env_index,
    hourly,
    morning_window,
    summarize,
)

UTC = timezone.utc


def _local(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 10, day, hour, minute, tzinfo=FIELD_TZ)


def _series(start: datetime, hours: int, temp: float, rh: float, *, per_hour: int = 2, wetness=None):
    """从 start 起每小时 per_hour 条同值读数。"""
    return [
        Reading(start + timedelta(hours=h, minutes=30 * k), temp, rh, wetness)
        for h in range(hours) for k in range(per_hour)
    ]


def test_dew_point_known_values():
    # Magnus（a=17.62, b=243.12）：20℃/50% → 9.26℃；饱和时露点等于气温
    assert dew_point(20, 50) == pytest.approx(9.26, abs=0.01)
    assert dew_point(25, 85) == pytest.approx(22.30, abs=0.01)
    assert dew_point(10, 100) == pytest.approx(10.0, abs=1e-9)
    assert dew_point(10, 0) is None


def test_hourly_aggregates_and_marks_missing_hours_without_interpolating():
    start = _local(1, 0)
    readings = [Reading(start, 18, 80), Reading(start + timedelta(minutes=30), 20, 90),
                Reading(start + timedelta(hours=2), 16, 99, 0.7)]
    hours = hourly(readings, start, start + timedelta(hours=3))
    assert [h["count"] for h in hours] == [2, 0, 1]
    assert hours[0]["temp_c"] == 19 and hours[0]["humidity_pct"] == 85
    assert hours[0]["dewpoint_depression_min"] == pytest.approx(20 - dew_point(20, 90))
    assert hours[1] == {"hour": (start + timedelta(hours=1)).astimezone(UTC), "count": 0, "missing": True,
                        "temp_c": None, "humidity_pct": None, "dewpoint_depression_min": None,
                        "leaf_wetness_max": None}
    assert hours[2]["leaf_wetness_max"] == 0.7


def test_daily_metrics_on_constructed_day():
    # 10 月 1 日（东八区）：0–6 点 16℃/96%（适宜且湿润），6–12 点 22℃/80%（都不是），
    # 12–18 点 27℃/90%（太热不适宜，也不湿润），18–24 点 18℃/86% 叶面湿度 0.6（适宜且湿润）
    readings = (_series(_local(1, 0), 6, 16, 96) + _series(_local(1, 6), 6, 22, 80)
                + _series(_local(1, 12), 6, 27, 90) + _series(_local(1, 18), 6, 18, 86, wetness=0.6)
                + _series(_local(2, 0), 4, 15, 97))  # 次日凌晨 0–4 点湿润，算进 1 日的夜晚
    hours = hourly(readings, _local(1, 0), _local(2, 8))
    days = {d["field_date"]: d for d in daily(hours)}
    day1 = days[date(2026, 10, 1)]
    assert day1["favorable_hours"] == 12
    assert day1["wet_hours"] == 12
    assert day1["night_wet_hours"] == 6 + 4  # 1 日 18–24 点 + 2 日 0–4 点
    assert day1["night_coverage"] == pytest.approx(10 / 14, abs=1e-4)
    assert day1["diurnal_range"] == 11  # 27 − 16
    assert day1["coverage"] == 1.0
    day2 = days[date(2026, 10, 2)]
    assert day2["coverage"] == pytest.approx(4 / 24, abs=1e-4)
    assert day2["night_wet_hours"] == 0 and day2["night_coverage"] == 0


def test_env_index_formula_and_components():
    as_of = _local(4, 0)
    readings = _series(as_of - timedelta(hours=72), 72, 22, 75)  # 全覆盖、都不适宜
    readings += _series(as_of - timedelta(hours=10), 10, 18, 96)  # 最后 10 小时又适宜又湿润（同一小时取均值）
    hours = hourly(readings, as_of - timedelta(hours=72), as_of)
    result = env_index(hours, as_of)
    # 后 10 小时的均值是 (22+18)/2=20℃、(75+96)/2=85.5% → 适宜不湿润；但最小露点差取 18℃/96% 那条 → 湿润
    assert result["favorable_hours"] == 10 and result["wet_hours"] == 10 and result["coverage"] == 1.0
    assert result["env_index"] == pytest.approx(1 - 2.718281828 ** (-20 / 24), abs=1e-4)


def test_env_index_is_none_when_coverage_insufficient():
    as_of = _local(4, 0)
    readings = _series(as_of - timedelta(hours=30), 30, 18, 96)  # 72 小时里只有 30 小时有数据
    result = env_index(hourly(readings, as_of - timedelta(hours=72), as_of), as_of)
    assert result["coverage"] == pytest.approx(30 / 72, abs=1e-4)
    assert result["env_index"] is None and "无环境信息" in result["reason"]


def test_morning_window_triggers_after_wet_night():
    readings = _series(_local(1, 18), 14, 16, 97)  # 1 日 18:00 到 2 日 08:00 全湿润
    summary = summarize(readings, as_of=_local(2, 9), plan_date=date(2026, 10, 2))
    window = summary["morning_window"]
    assert window is not None and window["start"] == "05:30" and window["end"] == "08:30"
    assert window["night_of"] == date(2026, 10, 1) and window["night_wet_hours"] == 14


def test_morning_window_not_triggered_after_dry_night():
    readings = _series(_local(1, 18), 14, 16, 70)
    summary = summarize(readings, as_of=_local(2, 9), plan_date=date(2026, 10, 2))
    assert summary["morning_window"] is None


def test_morning_window_falls_back_to_previous_night_when_last_night_has_no_data():
    # 前一天傍晚就排第二天的计划：计划日前一夜还没数据，改看再前一夜
    readings = _series(_local(1, 18), 14, 16, 97)
    days = daily(hourly(readings, _local(1, 0), _local(3, 0)))
    window = morning_window(days, date(2026, 10, 3))
    assert window is not None and window["night_of"] == date(2026, 10, 1)
    assert morning_window(days, date(2026, 10, 5)) is None  # 两夜都没数据：不给建议
