"""大棚黄瓜模拟世界的无网络单元测试（仓库根目录运行：python -m unittest simulator.test_greenhouse）。"""
from __future__ import annotations

import json
import random
import unittest
from datetime import date

from simulator.greenhouse import (
    TRUTH_SCHEMA, DiseaseParams, HourEnv, Layout, VisibilityParams, diurnal_range, human_label, run_disease,
    sample_photo, shoot_view, simulate, to_truth,
)


def _flat_env(days: int, wet_hours_per_day: int, temp_c: float = 18.0) -> list[HourEnv]:
    """每天前 wet_hours_per_day 个小时湿润、温度适宜，其余干燥。"""
    return [HourEnv(d, h, temp_c, 97.0 if h < wet_hours_per_day else 70.0, h < wet_hours_per_day)
            for d in range(days) for h in range(24)]


class GreenhouseWorldTests(unittest.TestCase):
    def test_same_seed_same_world(self) -> None:
        a = simulate(Layout(rows=3, plants_per_row=20), seed=11, days=20)
        b = simulate(Layout(rows=3, plants_per_row=20), seed=11, days=20)
        self.assertEqual(a.env, b.env)
        self.assertEqual(a.plants, b.plants)
        c = simulate(Layout(rows=3, plants_per_row=20), seed=12, days=20)
        self.assertNotEqual(a.env, c.env)

    def test_plastic_tunnel_has_larger_diurnal_range(self) -> None:
        solar = simulate(Layout(facility_type="solar_greenhouse"), seed=3, days=20)
        tunnel = simulate(Layout(facility_type="plastic_tunnel"), seed=3, days=20)
        self.assertGreater(diurnal_range(tunnel.env), diurnal_range(solar.env) + 3.0)

    def test_states_progress_in_order(self) -> None:
        world = simulate(Layout(), seed=5, days=30)
        params = world.disease
        for plant in world.plants.values():
            codes = world.daily_codes(plant.key)
            self.assertEqual(len(codes), world.days + world.extra_days)
            order = "HLES"
            self.assertEqual(list(codes), sorted(codes, key=order.index), plant.key)  # 只能往后走，不会恢复
            if plant.infected_hour is not None:
                latent = (plant.early_hour - plant.infected_hour) / 24
                early = (plant.symptomatic_hour - plant.early_hour) / 24
                self.assertTrue(params.latent_days[0] <= latent <= params.latent_days[1])
                self.assertTrue(params.early_days[0] <= early <= params.early_days[1])

    def test_more_wet_hours_more_infections(self) -> None:
        layout = Layout(rows=4, plants_per_row=30)
        params = DiseaseParams(beta=0.0)  # 只看环境项，排除传播带来的方差
        totals = []
        for wet_hours in (2, 6, 12):
            env = _flat_env(20, wet_hours)
            infected = 0
            for seed in range(8):
                plants = run_disease(layout, env, params, random.Random(seed))
                infected += sum(1 for p in plants.values() if p.infected_hour is not None)
            totals.append(infected)
        self.assertLess(totals[0], totals[1])
        self.assertLess(totals[1], totals[2])

    def test_cold_wet_hours_do_not_infect(self) -> None:
        plants = run_disease(Layout(rows=2, plants_per_row=10), _flat_env(20, 24, temp_c=8.0),
                             DiseaseParams(base_rate=0.5), random.Random(1))
        self.assertTrue(all(p.infected_hour is None for p in plants.values()))

    def test_spread_from_symptomatic_neighbours(self) -> None:
        layout = Layout(rows=5, plants_per_row=21)
        focus = Layout.key(3, 11)
        env = _flat_env(3, 10)
        near = {Layout.key(r, p) for r in (2, 3, 4) for p in (10, 11, 12)} - {focus}
        spread = DiseaseParams(base_rate=0.0, beta=0.02)
        hit_near = hit_far = 0
        for seed in range(10):
            plants = run_disease(layout, env, spread, random.Random(seed), initial_symptomatic=[focus])
            infected = {k for k, p in plants.items() if p.infected_hour is not None and k != focus}
            hit_near += len(infected & near)
            hit_far += len(infected - near)
        self.assertGreater(hit_near, 0)
        self.assertEqual(hit_far, 0)  # 3 天内新侵染的株还在潜伏期，不会再往外传
        none = run_disease(layout, env, DiseaseParams(base_rate=0.0, beta=0.0), random.Random(0),
                           initial_symptomatic=[focus])
        self.assertTrue(all(p.infected_hour is None for k, p in none.items() if k != focus))

    def test_visibility_parameters_change_detection_rate(self) -> None:
        def rate(params: VisibilityParams, period: str) -> float:
            rng = random.Random(7)
            shots = [sample_photo(rng, "early", "under", period, 1, params) for _ in range(4000)]
            accepted = [s for s in shots if s.accepted]
            return sum(s.detected for s in accepted) / len(accepted)

        default = VisibilityParams()
        self.assertAlmostEqual(rate(default, "morning"), 0.70, delta=0.04)
        self.assertAlmostEqual(rate(default, "day"), 0.35, delta=0.04)
        blind = VisibilityParams()
        blind.detect["early"]["under"]["morning"] = 0.1
        self.assertAlmostEqual(rate(blind, "morning"), 0.10, delta=0.03)

    def test_reshoot_retries_until_accepted(self) -> None:
        params = VisibilityParams(reject={"under": 1.0, "upper": 0.0}, reshoot_success=0.0, max_attempts=3)
        rng = random.Random(0)
        self.assertEqual([p.attempt for p in shoot_view(rng, "early", "under", "day", params, reshoot=True)], [1, 2, 3])
        self.assertEqual(len(shoot_view(rng, "early", "under", "day", params, reshoot=False)), 1)
        self.assertEqual(len(shoot_view(rng, "early", "upper", "day", params, reshoot=True)), 1)

    def test_human_label_follows_latest_visible_lesion(self) -> None:
        rng = random.Random(0)
        self.assertEqual(human_label(rng, [("early", True)], error=0.0), "downy_mildew_early")
        self.assertEqual(human_label(rng, [("early", True), ("symptomatic", True)], error=0.0), "downy_mildew_symptomatic")
        self.assertEqual(human_label(rng, [("symptomatic", False)], error=0.0), "normal")  # 照片上看不出
        self.assertEqual(human_label(rng, [("healthy", True)], error=0.0), "normal")  # 误检，人能认出来
        flipped = {human_label(rng, [("early", True)], error=1.0) for _ in range(50)}
        self.assertEqual(flipped, {"normal", "downy_mildew_symptomatic"})

    def test_truth_export_is_complete_and_serialisable(self) -> None:
        world = simulate(Layout(rows=2, plants_per_row=5), seed=4, days=6, extra_days=3, pre_days=2)
        truth = json.loads(json.dumps(to_truth(world, date(2026, 3, 2))))
        self.assertEqual(truth["schema"], TRUTH_SCHEMA)
        self.assertIn("只证明流程", truth["note"])
        self.assertEqual(len(truth["env_hourly"]), (2 + 6 + 3) * 24)
        self.assertEqual(truth["env_hourly"][0]["at"], "2026-02-28T00:00:00+08:00")
        self.assertEqual(len(truth["plants"]), 10)
        self.assertTrue(all(len(codes) == 9 for codes in truth["daily_states"].values()))
        self.assertIsNone(truth["closed_loop"])


if __name__ == "__main__":
    unittest.main()
