"""天气曲线生成：日变化正弦 + 轻噪声；土壤墒情可沿巡检进度线性衰减（干旱场景）。"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass


@dataclass(slots=True)
class WeatherProfile:
    base_temp_c: float = 24.0        # 巡检时段平均气温
    temp_amplitude_c: float = 4.0    # 时段内波动幅度
    base_humidity_pct: float = 60.0
    wind_mps: float = 1.8
    light_lux_noon: float = 85_000.0
    soil_moisture_start: float = 72.0
    soil_moisture_end: float = 70.0   # dry 场景会调低
    rain_mm: float = 0.0


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def weather_at(minutes_of_day: int, progress: float, profile: WeatherProfile,
               rng: random.Random) -> dict:
    """progress ∈ [0,1] 为该点在整趟巡检中的位置。"""
    # 气温：以 14:00(840min) 为峰的正弦
    phase = math.pi * (minutes_of_day - 480) / 720.0  # 08:00→20:00 半个周期
    temp = profile.base_temp_c + profile.temp_amplitude_c * math.sin(_clamp(phase, -math.pi / 2, math.pi / 2))
    temp += rng.uniform(-0.6, 0.6)

    humidity = _clamp(
        profile.base_humidity_pct - (temp - profile.base_temp_c) * 5.5
        + rng.uniform(-3, 3),
        15, 98,
    )
    light = max(0.0, profile.light_lux_noon * math.sin(math.pi * (minutes_of_day - 380) / 920))
    light *= rng.uniform(0.92, 1.05)
    wind = _clamp(profile.wind_mps + rng.uniform(-0.5, 0.5), 0, 15)
    soil = _clamp(
        profile.soil_moisture_start
        + (profile.soil_moisture_end - profile.soil_moisture_start) * progress
        + rng.uniform(-1.5, 1.5),
        5, 95,
    )
    return {
        "temp_c": round(temp, 1),
        "humidity_pct": round(humidity, 1),
        "light_lux": round(light),
        "wind_mps": round(wind, 1),
        "rain_mm": profile.rain_mm,
        "soil_temp_c": round(temp - rng.uniform(1.5, 3.5), 1),
        "soil_moisture_pct": round(soil, 1),
    }
