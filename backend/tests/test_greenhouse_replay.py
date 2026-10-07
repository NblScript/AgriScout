"""计划 0017：大棚巡检策略离线比较（纯函数，手写小真值）。"""
import json
from datetime import date, datetime, timedelta, timezone

import pytest

from app.services import greenhouse_replay as gr
from app.services import patrol_planner
from app.services.patrol_planner import PlanItem

TZ = timezone(timedelta(hours=8))
DAY0 = date(2026, 3, 2)


def _visibility(early=1.0, symptomatic=1.0, background=0.0, reject=0.0):
    def table(p):
        return {"under": {"morning": p, "day": p}, "upper": {"morning": p, "day": p}}
    return {
        "detect": {"healthy": table(background), "latent": table(background), "early": table(early),
                   "symptomatic": table(symptomatic)},
        "reject": {"under": reject, "upper": reject}, "reshoot_success": 1.0, "max_attempts": 3,
    }


def _plant(pos, early_day=None, symptomatic_day=None, early_hour=0):
    key = f"R01-P{pos:03d}"
    if early_day is None:
        return {"key": key, "row": 1, "pos": pos, "infected_hour": None, "early_hour": None, "symptomatic_hour": None}
    return {"key": key, "row": 1, "pos": pos, "infected_hour": 0, "early_hour": early_day * 24 + early_hour,
            "symptomatic_hour": symptomatic_day * 24}


def _truth(*, seed=1, days=6, plants=None, visibility=None, wet_nights=False, human_error=0.0):
    """1 垄 6 株：P002 第 2 天早期、第 4 天明显；P005 第 1 天早期、第 3 天明显；P006 第 5 天早期、第 7 天明显；
    P004 第 5 天 10 点才进早期（每天 8 点取状态，季内不算病株）。"""
    plants = plants or [_plant(1), _plant(2, 2, 4), _plant(3), _plant(4, 5, 8, early_hour=10), _plant(5, 1, 3),
                        _plant(6, 5, 7)]
    start = datetime.combine(DAY0, datetime.min.time(), tzinfo=TZ)
    env = []
    for h in range(-4 * 24, (days + 4) * 24):
        night = h % 24 >= 18 or h % 24 < 8
        env.append({"at": (start + timedelta(hours=h)).isoformat(), "temp_c": 18.0,
                    "humidity_pct": 97.0 if wet_nights and night else 70.0})
    return {
        "schema": gr.TRUTH_SCHEMA, "seed": seed, "facility_type": "solar_greenhouse",
        "layout": {"rows": 1, "plants_per_row": len(plants)}, "day0": DAY0.isoformat(), "days": days,
        "extra_days": 4, "state_hour": 8, "env_hourly": env, "plants": plants,
        "visibility": visibility or _visibility(),
        "photo_scores": {"symptomatic": 0.85, "early": 0.55, "false_positive": 0.5, "none": 0.1},
        "human_error": human_error,
    }


def test_metrics_on_hand_written_confirmations():
    truth = gr.load_truth(_truth())
    confirmations = [
        gr.Confirmation("R01-P001", 1, "normal", "healthy"),  # 无效确认
        gr.Confirmation("R01-P003", 2, "downy_mildew_early", "healthy"),  # 把健康株确认为病
        gr.Confirmation("R01-P002", 3, "downy_mildew_early", "early"),  # 第 4 天明显 → 提前 1 天
        gr.Confirmation("R01-P002", 5, "downy_mildew_symptomatic", "symptomatic"),  # 只算第一次
        gr.Confirmation("R01-P005", 4, "downy_mildew_symptomatic", "symptomatic"),  # 第 3 天明显 → 晚 1 天
    ]
    m = gr.season_metrics(truth, confirmations, [3, 4, 5])
    assert m == {
        "diseased": 3,  # P002、P005、P006；P004 第 5 天 8 点还在潜伏期
        "confirmed": 2, "missed": 1, "confirmed_before_symptomatic": 1,
        "lead_days_mean": 0.0, "lead_days": [-1, 1],
        "photos": 12, "confirmations": 5, "invalid_confirmations": 1, "false_positive_confirmations": 1,
    }


def test_fixed_strategy_end_to_end_on_deterministic_truth():
    # 可见性 0/1、无不合格、无人工误判：k=2 时单号株在双数天、双号株在单数天拍，人工预算 3 = 当天拍过的全部株
    truth = gr.load_truth(_truth())
    run = gr.run_strategy(truth, "fixed", gr.ReplayParams(fixed_every_days=2, human_budget=3))
    assert run.daily_photos == [6] * 6 and run.photo_cap == 6
    positives = [(c.day, c.key) for c in run.confirmations if c.label != "normal"]
    assert positives == [(2, "R01-P005"), (3, "R01-P002"), (4, "R01-P005"), (5, "R01-P002"), (5, "R01-P006")]
    m = gr.season_metrics(truth, run.confirmations, run.daily_photos)
    assert (m["confirmed"], m["missed"], m["lead_days"]) == (3, 0, [1, 1, 2])
    assert (m["confirmations"], m["invalid_confirmations"], m["false_positive_confirmations"]) == (18, 13, 0)


def test_all_strategies_share_the_same_budget():
    params = gr.ReplayParams(fixed_every_days=2, human_budget=2, photo_cap=4)
    report = gr.run_replay([_truth(visibility=_visibility(reject=0.3))], params)
    runs = report["seeds"][0]["strategies"]
    assert set(runs) == set(gr.STRATEGIES)
    assert {json.dumps(r["budget"], sort_keys=True) for r in runs.values()} == {'{"human_budget": 2, "photo_cap": 4}'}
    for r in runs.values():
        assert max(r["daily_photos"]) <= 4 and max(r["daily_confirms"]) <= 2
    assert runs["risk"]["daily_photos"][0] == 4  # 第 0 天 6 株都没见过，照片上限起作用


def test_default_photo_cap_lets_fixed_cover_everything():
    assert gr.ReplayParams(fixed_every_days=3).cap_for(120) == 80
    assert gr.ReplayParams(photo_cap=50).cap_for(120) == 50
    with pytest.raises(ValueError):
        gr.ReplayParams(strategies=("random_walk",))


def test_risk_strategy_calls_the_production_planner(monkeypatch):
    assert gr.patrol_planner is patrol_planner  # 同一份实现，不是复制
    calls = []
    original = patrol_planner.build_plan

    def spy(units, env, **kwargs):
        calls.append((kwargs["plan_date"], len(units), env["index"]["env_index"]))
        return original(units, env, **kwargs)

    monkeypatch.setattr(patrol_planner, "build_plan", spy)
    truth = gr.load_truth(_truth())
    run = gr.run_strategy(truth, "risk", gr.ReplayParams(human_budget=2))
    assert run.planner_calls == 6
    assert [c[0] for c in calls] == [DAY0 + timedelta(days=d) for d in range(6)]
    assert all(n == 6 for _, n, _ in calls)

    # 拍哪些株完全由 planner 的名单决定：换成只抽查 P003 的计划，就只拍 P003 的正面和叶背
    def stub(units, env, **kwargs):
        lists = {name: [] for name in patrol_planner.LISTS}
        lists["random"] = [PlanItem(3, "R01-P003", "random", 0.1, 0.1, {})]
        return {"window": None, "lists": lists}

    monkeypatch.setattr(patrol_planner, "build_plan", stub)
    run = gr.run_strategy(truth, "risk", gr.ReplayParams(human_budget=2))
    assert run.daily_photos == [2] * 6 and run.confirmations == []


def test_risk_strategy_shoots_in_the_morning_window():
    truth = gr.load_truth(_truth(wet_nights=True))
    assert gr.run_strategy(truth, "risk").periods == ["morning"] * 6
    assert gr.run_strategy(truth, "fixed").periods == ["day"] * 6


def test_same_truth_same_report():
    vis = _visibility(early=0.6, symptomatic=0.9, background=0.05, reject=0.25)
    truths = [_truth(seed=s, visibility=vis, human_error=0.1, wet_nights=s % 2 == 0) for s in (3, 4)]
    a = gr.run_replay(truths, gr.ReplayParams(fixed_every_days=2, human_budget=2))
    b = gr.run_replay(json.loads(json.dumps(truths)), gr.ReplayParams(fixed_every_days=2, human_budget=2))
    assert json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)
    md = gr.render_markdown(a)
    assert md == gr.render_markdown(b)
    assert md.startswith("# 大棚巡检策略离线比较") and "模拟结论只证明流程" in md.splitlines()[2]
    assert a["summary"]["risk"]["diseased"]["mean"] == 3


def test_aggregate_and_truth_schema():
    assert gr.aggregate(list(range(1, 11))) == {"mean": 5.5, "p10": 1.9, "p90": 9.1, "n": 10}
    assert gr.aggregate([None, 2.0]) == {"mean": 2.0, "p10": 2.0, "p90": 2.0, "n": 1}
    assert gr.aggregate([None])["mean"] is None
    with pytest.raises(ValueError):
        gr.load_truth({**_truth(), "schema": "agriscout.season-truth.v1"})
