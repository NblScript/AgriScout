"""离线重放（纯函数）：用确定性的「同心圆扩散」小世界检验 H1/H2/H3 的逻辑与不变量。"""
import pytest

from app.services.offline_replay import (
    FEATURE_SETS,
    ReplayInput,
    build_samples,
    fit_logistic,
    h1_ablation,
    h2_revisit_replay,
    h3_active_learning,
    labeled,
    out_of_fold,
    run_replay,
)

RING_VISIBLE_DAY = {0: 3, 1: 9, 2: 15}  # 中心 → 第一圈 → 第二圈依次显症；最外圈不发病


def _ring_world() -> ReplayInput:
    regions, truth, image = {}, {}, {}
    days = [0, 3, 6, 9, 12, 15, 18, 21]
    for ix in range(6):
        for iy in range(6):
            key = f"r{ix}_{iy}"
            regions[key] = (ix, iy)
            ring = max(abs(ix - 2), abs(iy - 2))
            v = RING_VISIBLE_DAY.get(ring)
            series = [0.0 if v is None or d < v else min(1.0, 0.06 + 0.12 * (d - v)) for d in range(30)]
            truth[key] = series
            for d in days:  # 基础巡检只在严重度 ≥ 0.3 时拍得到
                image[(key, d)] = round(series[d] * 0.5, 3) if series[d] >= 0.3 else 0.0
    weather = [{"favourability": 0.6, "rain_mm": 2.0, "humidity_pct": 80.0} for _ in range(30)]
    return ReplayInput(days, regions, 2.5, image, truth, weather, horizon_days=3)


def test_labels_follow_first_symptom_definition_and_features_never_see_truth():
    inp = _ring_world()
    samples = build_samples(inp)
    # 第一圈在第 9 天尚未显症（0.06 < 0.1），第 10 天显症 → 第 9 天样本为阳性
    s = next(x for x in samples if x.region == "r1_2" and x.day == 9)
    assert s.label == 1 and s.features["img_now"] == 0.0 and s.features["nbr_now"] > 0.3
    # 已显症的区域-日不带标签（不属于首次显症任务），但仍有特征供 H2 打分
    assert next(x for x in samples if x.region == "r2_2" and x.day == 9).label is None
    # 最外圈永不发病
    assert all(x.label == 0 for x in samples if x.region == "r5_5")


def test_logistic_regression_orders_and_degrades_to_constant():
    rows = [{"a": float(i)} for i in range(20)]
    labels = [int(i >= 12) for i in range(20)]
    model = fit_logistic(rows, labels, ["a"])
    assert model.predict({"a": 19.0}) > 0.9 > 0.1 > model.predict({"a": 0.0})
    constant = fit_logistic(rows, [0] * 20, ["a"])
    assert constant.predict({"a": 0.0}) == constant.predict({"a": 19.0}) < 0.05


def test_h1_spatial_neighbours_beat_image_only_when_symptoms_are_latent():
    report, _ = h1_ablation(build_samples(_ring_world()), bootstrap=50)
    assert report["full"]["pr_auc"] > report["image"]["pr_auc"] + 0.3
    assert set(report) >= set(FEATURE_SETS)


def test_out_of_fold_never_trains_on_its_own_fold():
    samples = build_samples(_ring_world())
    # 把第 0 组的标签全部翻转：若泄漏，第 0 组的预测会学到翻转后的标签
    poisoned = [None if s.label is None else (1 - s.label if s.fold == 0 else s.label) for s in samples]
    clean = out_of_fold(samples, FEATURE_SETS["full"])
    dirty = out_of_fold(samples, FEATURE_SETS["full"], labels=poisoned)
    fold0 = [i for i, s in enumerate(samples) if s.fold == 0]
    assert [clean[i] for i in fold0] == [dirty[i] for i in fold0]


def test_h2_budget_and_risk_ranking_beats_random():
    inp = _ring_world()
    samples = build_samples(inp)
    nowcast = {(s.region, s.day): (1.0 if inp.severity(s.region, s.day) >= 0.05 else 0.0) for s in samples}
    report = h2_revisit_replay(inp, samples, nowcast, budget_frac=0.1, seed=1)
    budget = report["budget_per_patrol"]
    for row in report["strategies"].values():
        assert row["visits"] <= budget * len(inp.patrol_days)
        assert row["found"] <= report["diseased_regions"]
    # 完美的现时检出排序应当至少和随机一样好，且能在基础巡检看见之前确认
    assert report["strategies"]["risk_model"]["found"] >= report["strategies"]["random"]["found"]
    assert report["strategies"]["risk_model"]["found_before_base_visible"] > 0


def test_h3_curves_share_the_same_starting_point_and_budget():
    samples = labeled(build_samples(_ring_world()))
    report = h3_active_learning(samples, seeds=(0,), init=10, step=10, budget=40)
    firsts = {curve[0][0] for curve in report["curves"].values()}
    first_aps = {curve[0][1] for curve in report["curves"].values()}
    assert firsts == {10} and len(first_aps) == 1  # 相同初始样本 → 相同起点
    assert all(curve[-1][0] <= 40 for curve in report["curves"].values())


def test_run_replay_is_deterministic():
    inp = _ring_world()
    a = run_replay(inp, al_seeds=(0,))
    b = run_replay(inp, al_seeds=(0,))
    assert a == b
    assert a["data"]["positives"] > 0 and a["limitations"]


def test_replay_input_severity_clamps_to_series_end():
    inp = _ring_world()
    assert inp.severity("r2_2", 999) == inp.truth_severity["r2_2"][-1]
    assert inp.severity("missing", 3) == 0.0
    with pytest.raises(KeyError):
        _ = inp.regions["missing"]


def test_replay_eval_loads_platform_data_and_truth(client):
    """CLI 的读库路径：采样点按平台网格归入区域，真值按 seq 对齐，平台预测按区域取最大。"""
    from app.core.db import get_session_factory
    from app.main import app
    from app.tools.replay_eval import TRUTH_SCHEMA, load_input
    from conftest import png_b64

    field_id = client.post("/api/v1/fields", json={
        "name": "重放田", "boundary": {"type": "Polygon", "coordinates": [[[10, 10], [10.001, 10], [10.001, 10.001], [10, 10]]]},
    }).json()["id"]
    client.post("/api/v1/devices", json={"code": "rp-01", "name": "重放车", "type": "rover"})
    patrols = []
    for day, date in ((0, "2026-09-01"), (3, "2026-09-04")):
        pkg = {"patrol": {"field_id": field_id, "device": "rp-01", "started_at": f"{date}T08:00:00+00:00"},
               "capture_points": [{"seq": i, "lng": 10.00001, "lat": 10.00001 + i * 5 / 111_320,
                                   "captured_at": f"{date}T08:0{i}:00+00:00",
                                   "photo": png_b64((120, 85, 50) if (day, i) == (3, 1) else (40, 160, 60))}
                                  for i in range(2)]}
        pid = client.post("/api/v1/ingest/patrol", json=pkg).json()["patrol_id"]
        client.post(f"/api/v1/patrols/{pid}/risk-predictions/generate", json={"target_event": "e", "forecast_hours": 72})
        patrols.append({"day": day, "patrol_id": pid})
    truth = {
        "schema": TRUTH_SCHEMA, "field_id": field_id, "target_event": "e", "model_version": "risk-heuristic-v2",
        "horizon_hours": 72, "event_severity": 0.1, "patrols": patrols,
        "weather": [{"favourability": 0.5, "rain_mm": 0.0, "humidity_pct": 70.0}] * 8,
        "severity": {"1": [0, 0, 0, 0.2, 0.4, 0.6, 0.8, 0.9]},
    }
    db = app.dependency_overrides[get_session_factory]()()
    try:
        inp = load_input(db, truth)
    finally:
        db.close()
    assert inp.patrol_days == [0, 3] and len(inp.regions) == 2  # 两个点相距 5 m，落在两个 2.5 m 网格
    diseased = [k for k, series in inp.truth_severity.items() if max(series) > 0]
    assert len(diseased) == 1
    assert inp.image_score[(diseased[0], 3)] > inp.image_score[(diseased[0], 0)]
    assert set(inp.platform_prob) == {(k, d) for k in inp.regions for d in (0, 3)}
    with pytest.raises(ValueError):
        load_input(app.dependency_overrides[get_session_factory]()(), {**truth, "schema": "other"})
