"""场景定义：一块田、一趟巡检里"种"什么问题。

- healthy        全程长势正常，墒情良好 → 仅生育期常规建议
- dry            全田土壤墒情持续走低 → 触发干旱阈值类规则（需匹配生育期）
- patchy_disease 中段聚集性枯黄斑块 → 触发胁迫检出/高风险复核类规则
"""
from __future__ import annotations

import random
from dataclasses import dataclass, field

from weather import WeatherProfile


@dataclass(slots=True)
class Scenario:
    name: str
    description: str
    profile: WeatherProfile = field(default_factory=WeatherProfile)

    def photo_spec(self, progress: float, rng: random.Random) -> tuple[str, float]:
        """返回 (photo_mode, intensity)。progress ∈ [0,1]。"""
        raise NotImplementedError

    @staticmethod
    def get(name: str) -> "Scenario":
        if name == "healthy":
            return HealthyScenario()
        if name == "dry":
            return DryScenario()
        if name == "patchy_disease":
            return PatchyDiseaseScenario()
        raise ValueError(f"未知场景：{name}（可选 healthy / dry / patchy_disease）")


class HealthyScenario(Scenario):
    def __init__(self) -> None:
        super().__init__("healthy", "全田健康：仅常规生育期建议")

    def photo_spec(self, progress: float, rng: random.Random):
        return ("healthy", 0.0)


class DryScenario(Scenario):
    def __init__(self) -> None:
        super().__init__(
            "dry",
            "全田干旱：墒情沿巡检进度持续走低，触发干旱阈值规则",
            WeatherProfile(soil_moisture_start=68.0, soil_moisture_end=30.0),
        )

    def photo_spec(self, progress: float, rng: random.Random):
        # 后半程轻度胁迫（旱象上叶）
        if progress > 0.6 and rng.random() < 0.5:
            return ("stress", 0.25 * (progress - 0.6) / 0.4 + 0.1)
        return ("healthy", 0.0)


class PatchyDiseaseScenario(Scenario):
    def __init__(self) -> None:
        super().__init__(
            "patchy_disease",
            "中段聚集性病害斑块：模拟病害空间聚集性（早期斑块<1m）",
            WeatherProfile(soil_moisture_start=70.0, soil_moisture_end=58.0),
        )

    def photo_spec(self, progress: float, rng: random.Random):
        if 0.35 <= progress <= 0.65:
            center = abs(progress - 0.5) / 0.15  # 越靠中心越重
            return ("stress", min(1.0, 1.1 - center))
        if rng.random() < 0.08:
            return ("stress", 0.2)
        return ("healthy", 0.0)
