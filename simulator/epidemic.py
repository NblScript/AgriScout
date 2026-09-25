"""病害扩散元胞模型：潜伏期 + 天气驱动 + 发病中心向外扩散（条锈病样，参数可调）。

给多日期模拟用的「真值世界」，刻意保留三个对预测有意义的结构：
1. **潜伏期**：侵染后要过 ``latent_days`` 天才看得见——只看本区域当前照片无法预测首次显症；
2. **空间扩散**：可见病斑（产孢）按距离核向邻近网格传播——邻域信息有预测价值；
3. **天气驱动**：湿度、叶面湿润时长决定当天的传播强度——环境信息有预测价值。

只用标准库、种子固定可复现；不依赖本目录其他模块，可在仓库根目录 ``from simulator import epidemic`` 测试。
这不是经过校准的农学模型，参数用于检验方法流程，不能当作真实病害规律引用。
"""
from __future__ import annotations

import math
import random
from dataclasses import asdict, dataclass, field


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


@dataclass(slots=True)
class EpidemicConfig:
    days: int = 36
    cell_m: float = 1.0              # 模拟网格边长（与平台的区域网格无关）
    foci: int = 3                    # 初侵染点（发病中心）数量
    seed_day_range: tuple[int, int] = (0, 8)
    latent_days: int = 10            # 侵染到可见
    latent_jitter: int = 2
    spread_radius_m: float = 3.0
    beta: float = 0.9                # 基础传播强度
    background: float = 0.0008       # 外来菌源的背景侵染概率（每格每天，乘天气适宜度）
    growth_days: float = 8.0         # 可见后严重度从约 0.05 长到约 0.95 的天数


@dataclass(slots=True)
class DailyWeather:
    day: int
    temp_c: float
    humidity_pct: float
    rain_mm: float
    leaf_wet_hours: float

    def favourability(self) -> float:
        """0–1 的天气适宜度：高湿、叶面湿润时间长、温度接近 13 ℃ 时最有利（条锈病样）。"""
        humid = _clamp((self.humidity_pct - 60.0) / 30.0)
        wet = _clamp(self.leaf_wet_hours / 12.0)
        temp = _clamp(1.0 - abs(self.temp_c - 13.0) / 10.0)
        return round(0.45 * humid + 0.35 * wet + 0.20 * temp, 4)


def generate_weather(days: int, rng: random.Random) -> list[DailyWeather]:
    """两状态马尔可夫链模拟连阴雨：雨天高湿、叶面湿润长；晴天湿度与湿润时间低。"""
    series: list[DailyWeather] = []
    raining = False
    for day in range(days):
        raining = rng.random() < (0.55 if raining else 0.2)
        temp = 13.0 + 5.0 * math.sin(day / max(days, 1) * math.pi) + rng.uniform(-3, 3)
        if raining:
            humidity, rain, wet = rng.uniform(82, 96), rng.uniform(2, 15), rng.uniform(8, 14)
        else:
            humidity, rain, wet = rng.uniform(50, 78), 0.0, rng.uniform(0, 6)
        series.append(DailyWeather(day, round(temp, 1), round(humidity, 1), round(rain, 1), round(wet, 1)))
    return series


@dataclass(slots=True)
class Epidemic:
    """在 width_m × length_m 的田块上逐日推进侵染过程。"""

    width_m: float
    length_m: float
    config: EpidemicConfig = field(default_factory=EpidemicConfig)
    infected_day: dict[tuple[int, int], int] = field(default_factory=dict)
    visible_day: dict[tuple[int, int], int] = field(default_factory=dict)

    @property
    def shape(self) -> tuple[int, int]:
        c = self.config.cell_m
        return max(1, math.ceil(self.width_m / c) + 1), max(1, math.ceil(self.length_m / c) + 1)

    def cell_of(self, x_m: float, y_m: float) -> tuple[int, int]:
        nx, ny = self.shape
        c = self.config.cell_m
        return min(nx - 1, max(0, math.floor(x_m / c))), min(ny - 1, max(0, math.floor(y_m / c)))

    def _kernel(self) -> list[tuple[int, int, float]]:
        c, radius = self.config.cell_m, self.config.spread_radius_m
        reach = math.ceil(radius / c)
        kernel = []
        for dx in range(-reach, reach + 1):
            for dy in range(-reach, reach + 1):
                dist = math.hypot(dx * c, dy * c)
                if (dx, dy) != (0, 0) and dist <= radius:
                    kernel.append((dx, dy, math.exp(-dist / (radius / 2))))
        return kernel

    def _infect(self, cell: tuple[int, int], day: int, rng: random.Random) -> None:
        cfg = self.config
        self.infected_day[cell] = day
        self.visible_day[cell] = day + cfg.latent_days + rng.randint(-cfg.latent_jitter, cfg.latent_jitter)

    def run(self, weather: list[DailyWeather], rng: random.Random) -> None:
        cfg = self.config
        nx, ny = self.shape
        kernel = self._kernel()
        seed_days = sorted(rng.randint(*cfg.seed_day_range) for _ in range(cfg.foci))
        for day, w in enumerate(weather[: cfg.days]):
            for seed_day in seed_days:
                if seed_day == day:
                    cell = (rng.randrange(nx), rng.randrange(ny))
                    if cell not in self.infected_day:
                        self._infect(cell, day, rng)
            fav = w.favourability()
            pressure: dict[tuple[int, int], float] = {}
            for sx, sy in self.visible_day:
                sev = self.severity(sx, sy, day)
                if sev <= 0:
                    continue
                for dx, dy, weight in kernel:
                    tx, ty = sx + dx, sy + dy
                    if 0 <= tx < nx and 0 <= ty < ny:
                        pressure[(tx, ty)] = pressure.get((tx, ty), 0.0) + sev * weight
            for ix in range(nx):
                for iy in range(ny):
                    cell = (ix, iy)
                    if cell in self.infected_day:
                        continue
                    p = 1.0 - math.exp(-cfg.beta * fav * pressure.get(cell, 0.0)) + cfg.background * fav
                    if rng.random() < p:
                        self._infect(cell, day, rng)

    def severity(self, ix: int, iy: int, day: float) -> float:
        """可见严重度 0–1：可见当天约 0.05，经 growth_days 天长到约 0.95；未可见为 0。"""
        vday = self.visible_day.get((ix, iy))
        if vday is None or day < vday:
            return 0.0
        g = self.config.growth_days
        return round(1.0 / (1.0 + math.exp(-(day - vday - g / 2) / (g / 6))), 4)

    def severity_at(self, x_m: float, y_m: float, day: float) -> float:
        return self.severity(*self.cell_of(x_m, y_m), day)

    def summary(self) -> dict:
        return {
            "config": asdict(self.config),
            "infected_cells": len(self.infected_day),
            "total_cells": self.shape[0] * self.shape[1],
        }
