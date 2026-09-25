"""病害扩散模型与模拟季日期的无网络单元测试（仓库根目录运行：python -m unittest simulator.test_epidemic）。"""
from __future__ import annotations

import random
import unittest

from simulator.epidemic import DailyWeather, Epidemic, EpidemicConfig, generate_weather


def _run(seed: int) -> Epidemic:
    rng = random.Random(seed)
    weather = generate_weather(30, rng)
    epi = Epidemic(9.0, 30.0, EpidemicConfig(days=30))
    epi.run(weather, rng)
    return epi


class EpidemicTests(unittest.TestCase):
    def test_same_seed_same_world(self) -> None:
        a, b = _run(11), _run(11)
        self.assertEqual(a.infected_day, b.infected_day)
        self.assertEqual(a.visible_day, b.visible_day)

    def test_symptoms_appear_only_after_latent_period(self) -> None:
        epi = _run(3)
        cfg = epi.config
        self.assertTrue(epi.infected_day)
        for cell, infected in epi.infected_day.items():
            visible = epi.visible_day[cell]
            self.assertGreaterEqual(visible - infected, cfg.latent_days - cfg.latent_jitter)
            self.assertEqual(epi.severity(*cell, visible - 0.5), 0.0)
            self.assertGreater(epi.severity(*cell, visible + cfg.growth_days), 0.9)

    def test_spread_is_spatially_clustered(self) -> None:
        """后期被侵染的格子大多挨着更早被侵染的格子（发病中心向外扩散）。"""
        epi = _run(7)
        early = {c for c, d in epi.infected_day.items() if d <= 15}
        late = [c for c, d in epi.infected_day.items() if d > 15]
        self.assertTrue(early and late)
        near = sum(
            1 for (x, y) in late
            if any(abs(x - ex) <= 3 and abs(y - ey) <= 3 for ex, ey in early)
        )
        self.assertGreater(near / len(late), 0.7)

    def test_wet_weather_is_more_favourable(self) -> None:
        wet = DailyWeather(0, 13.0, 92.0, 8.0, 12.0)
        dry = DailyWeather(0, 25.0, 50.0, 0.0, 0.0)
        self.assertGreater(wet.favourability(), 0.9)
        self.assertLess(dry.favourability(), 0.1)


if __name__ == "__main__":
    unittest.main()
