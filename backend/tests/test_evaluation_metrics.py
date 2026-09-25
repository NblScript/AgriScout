"""评估指标纯函数：PR-AUC / Brier / 等渗校准 / 固定误报召回率 / 事件提前量 / 标签口径。"""
from datetime import datetime, timedelta, timezone

import pytest

from app.services.evaluation_metrics import (
    IsotonicCalibrator,
    LabeledPrediction,
    WindowPrediction,
    average_precision,
    brier_score,
    evaluate_predictions,
    event_lead_times,
    label_of,
    recall_at_fp_budget,
)

T0 = datetime(2027, 4, 1, tzinfo=timezone.utc)


def test_average_precision_matches_sklearn_definition():
    # sklearn.metrics.average_precision_score([0,0,1,1],[0.1,0.4,0.35,0.8]) == 0.8333…
    assert average_precision([0.1, 0.4, 0.35, 0.8], [0, 0, 1, 1]) == pytest.approx(0.833333, abs=1e-6)
    assert average_precision([0.9, 0.1], [1, 0]) == 1.0
    assert average_precision([0.3, 0.2], [0, 0]) is None


def test_average_precision_ties_do_not_depend_on_order():
    a = average_precision([0.5, 0.5, 0.1], [1, 0, 0])
    b = average_precision([0.5, 0.5, 0.1], [0, 1, 0])
    assert a == b == 0.5


def test_brier_score():
    assert brier_score([1.0, 0.0], [1, 0]) == 0.0
    assert brier_score([0.5, 0.5], [1, 0]) == 0.25
    assert brier_score([], []) is None
    with pytest.raises(ValueError):
        brier_score([0.5], [2])


def test_isotonic_pools_violators_and_is_monotone():
    cal = IsotonicCalibrator.fit([0.1, 0.2, 0.3, 0.4], [0, 1, 0, 1])
    assert cal.values == (0.0, 0.5, 1.0)
    assert [cal.predict(x) for x in (0.05, 0.25, 0.3, 0.9)] == [0.0, 0.5, 0.5, 1.0]


def test_recall_at_fp_budget_picks_highest_recall_within_budget():
    scores = [0.9, 0.8, 0.7, 0.6, 0.5]
    labels = [1, 0, 1, 0, 1]
    units = ["d1", "d1", "d2", "d2", "d2"]  # 2 个地块·日
    # 预算 0.5 条/单位 → 最多 1 条误报：取到 0.7，召回 2/3
    result = recall_at_fp_budget(scores, labels, units, fp_per_unit=0.5)
    assert result["recall"] == pytest.approx(2 / 3, abs=1e-6)
    assert result["threshold"] == 0.7
    # 预算 0 → 只能取 0.9
    assert recall_at_fp_budget(scores, labels, units, fp_per_unit=0)["recall"] == pytest.approx(1 / 3, abs=1e-6)


def test_event_lead_time_reports_missed_events():
    preds = [
        WindowPrediction("r1", T0, T0 + timedelta(hours=72), 0.8),
        WindowPrediction("r1", T0 + timedelta(hours=24), T0 + timedelta(hours=96), 0.9),
        WindowPrediction("r2", T0, T0 + timedelta(hours=72), 0.2),  # 低于阈值
    ]
    events = [("r1", T0 + timedelta(hours=48)), ("r2", T0 + timedelta(hours=10))]
    result = event_lead_times(events, preds, threshold=0.5)
    assert result["warned"] == 1 and result["missed"] == 1 and result["missed_rate"] == 0.5
    assert result["median_lead_hours"] == 48.0  # 取最早的有效预警


def test_status_mapping_excludes_censored_and_unknown():
    assert label_of("confirmed_positive") == 1 and label_of("confirmed_negative") == 0
    assert label_of("intervened") is None and label_of("insufficient") is None and label_of(None) is None
    records = [
        LabeledPrediction(0.9, "confirmed_positive", "u1", 1),
        LabeledPrediction(0.2, "confirmed_negative", "u1", 2),
        LabeledPrediction(0.7, "intervened", "u1", 3),
        LabeledPrediction(0.1, "insufficient", "u1", 4),
        LabeledPrediction(0.5, None, "u1", 5),
    ]
    report = evaluate_predictions(records)
    assert report["evaluable"] == 2 and report["censored"] == 1
    assert report["status_counts"] == {
        "confirmed_negative": 1, "confirmed_positive": 1, "insufficient": 1,
        "intervened": 1, "no_follow_up": 1,
    }
    assert report["pr_auc"] == 1.0


def test_time_split_calibration_uses_earlier_half_only():
    # 前半段：分数 0.9 实际全阴性 → 校准后应把 0.9 压低，后半段 Brier 改善
    records = [LabeledPrediction(0.9, "confirmed_negative", "u", i) for i in range(10)]
    records += [LabeledPrediction(0.9, "confirmed_negative", "u", 10 + i) for i in range(9)]
    records += [LabeledPrediction(0.9, "confirmed_positive", "u", 30)]
    report = evaluate_predictions(records, calibrate=True)
    cal = report["calibration"]
    assert cal["n_fit"] == 10 and cal["n_eval"] == 10
    assert cal["brier_calibrated"] < cal["brier_raw"]
