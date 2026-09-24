"""区域级风险基线的纯函数测试。"""

from datetime import datetime, timezone

import pytest

from app.services.risk_prediction import (
    RegionObservation,
    RiskThresholds,
    predict_region_risk,
)


def test_rising_visual_history_and_wet_environment_produce_urgent_result():
    result = predict_region_risk(
        history=[
            {"captured_at": "2026-09-20T08:00:00+00:00", "risk_score": 0.20},
            {"captured_at": "2026-09-21T08:00:00+00:00", "risk_score": 0.52},
            {"captured_at": "2026-09-22T08:00:00+00:00", "risk_score": 0.82},
        ],
        environment={"humidity_pct": 92, "rain_24h_mm": 18},
        quality={"quality_score": 0.95},
        horizon_hours=48,
    )

    assert result.trend == "rising"
    assert result.level == "high"
    assert result.probability > 0.66
    assert result.confidence > 0.8
    assert result.recheck_window_hours[1] <= 24
    assert any("temporal_trend=rising" in item for item in result.evidence)
    assert any("environment_favourability" in item for item in result.evidence)


def test_quality_gate_reduces_confidence_and_probability_extremes():
    clear = predict_region_risk(
        history=[{"risk_score": 0.95}, {"risk_score": 0.90}],
        quality={"quality_score": 1.0},
    )
    poor = predict_region_risk(
        history=[{"risk_score": 0.95}, {"risk_score": 0.90}],
        quality={"quality_score": 0.1, "position_error_m": 1.8},
    )

    assert clear.probability > poor.probability
    assert clear.confidence > poor.confidence
    assert any("quality_gate=low" in item for item in poor.evidence)
    assert poor.recheck_window_hours[0] <= 12


def test_timestamp_order_is_used_and_as_of_creates_datetime_window():
    result = predict_region_risk(
        history=[
            {"observed_at": "2026-09-22T08:00:00+00:00", "disease_score": 0.8},
            {"observed_at": "2026-09-20T08:00:00+00:00", "disease_score": 0.1},
        ],
        as_of="2026-09-22T12:00:00+00:00",
    )

    assert result.trend == "rising"
    start, end = result.recheck_window
    assert start == datetime(2026, 9, 22, 18, tzinfo=timezone.utc)
    assert end == datetime(2026, 9, 23, 12, tzinfo=timezone.utc)
    assert result["risk_level"] == result.level
    assert result.to_dict()["suggested_recheck_time_window"][0].endswith("+00:00")


def test_missing_evidence_is_unknown_and_requests_short_recheck():
    result = predict_region_risk(history=[])

    assert result.level == "unknown"
    assert result.trend == "unknown"
    assert result.probability == 0.5
    assert result.confidence == 0.0
    assert result.recheck_window_hours == (12, 24)
    assert any("insufficient evidence" in item for item in result.evidence)


def test_typed_observations_and_observations_alias_are_supported():
    result = predict_region_risk(
        observations=[
            RegionObservation(risk_score=0.15, quality={"score": 0.9}),
            RegionObservation(risk_score=0.20, quality={"score": 0.9}),
        ],
        environment={"environment_risk": 0.1},
    )

    assert result.level == "low"
    assert result.trend == "stable"
    assert result.feature_values["environment_favourability"] == 0.1


def test_thresholds_and_invalid_horizon_are_validated():
    result = predict_region_risk(
        history=[{"risk_score": 0.55}],
        thresholds=RiskThresholds(low_max=0.2, medium_max=0.5),
    )
    assert result.level == "high"

    with pytest.raises(ValueError):
        predict_region_risk(history=[], horizon_hours=0)
    with pytest.raises(ValueError):
        RiskThresholds(low_max=0.7, medium_max=0.6)
