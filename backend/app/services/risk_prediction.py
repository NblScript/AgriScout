"""区域级病害风险基线预测。

这个模块提供一个不依赖数据库、模型文件或 Web 框架的可解释基线。它把同一
观察区域的历史观测、环境条件和数据质量聚合成一个风险结果，供后续接口或
离线实验调用。真正的监督学习模型可以在不改变调用方的情况下替换它。

这里的 ``probability`` 是在给定预测窗口内发生目标事件的基线概率，不是对
尚无可见症状的感染作出诊断。低质量或缺失证据会降低置信度，并把概率向
0.5 收缩；这比把缺失数据当成“健康”或“高风险”更适合安排复查。
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Iterator, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from typing import Any, Literal


Trend = Literal["rising", "stable", "falling", "unknown"]
RiskLevel = Literal["low", "medium", "high", "unknown"]


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _number(value: Any) -> float | None:
    """Convert finite numeric values to float; invalid/missing values are ignored."""

    if isinstance(value, bool):
        return float(value)
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    return converted if math.isfinite(converted) else None


def _normalise_score(value: Any) -> float | None:
    """Normalise a score that is commonly expressed as 0..1 or 0..100."""

    converted = _number(value)
    if converted is None:
        return None
    if converted > 1.0 and converted <= 100.0:
        converted /= 100.0
    return _clamp(converted)


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _first(item: Mapping[str, Any], *keys: str) -> Any:
    """Read the first present key, including a nested ``features`` mapping."""

    containers = [
        item,
        _as_mapping(item.get("features")),
        _as_mapping(item.get("visual")),
        _as_mapping(item.get("visual_features")),
        _as_mapping(item.get("observation")),
        _as_mapping(item.get("signals")),
    ]
    for container in containers:
        for key in keys:
            if key in container:
                return container[key]
    return None


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class RegionObservation:
    """One already-associated observation for an observation region.

    Callers may pass dictionaries directly to :func:`predict_region_risk`; this
    dataclass is useful when a typed input is preferred. ``risk_score`` and
    ``disease_score`` are interchangeable visual risk signals in the baseline.
    """

    observed_at: datetime | date | str | None = None
    risk_score: float | None = None
    disease_score: float | None = None
    severity: float | None = None
    anomaly_score: float | None = None
    disease_detected: bool | None = None
    environment: Mapping[str, Any] = field(default_factory=dict)
    quality: Mapping[str, Any] = field(default_factory=dict)
    features: Mapping[str, Any] = field(default_factory=dict)

    def as_mapping(self) -> dict[str, Any]:
        return {
            "observed_at": self.observed_at,
            "risk_score": self.risk_score,
            "disease_score": self.disease_score,
            "severity": self.severity,
            "anomaly_score": self.anomaly_score,
            "disease_detected": self.disease_detected,
            "environment": dict(self.environment),
            "quality": dict(self.quality),
            "features": dict(self.features),
        }


@dataclass(frozen=True, slots=True)
class RiskPrediction(Mapping[str, Any]):
    """Region-level prediction returned by :func:`predict_region_risk`.

    ``recheck_window_hours`` is an inclusive ``(earliest, latest)`` offset from
    ``as_of``. If an ``as_of`` value was supplied, ``recheck_window`` contains
    the corresponding datetimes as well. The mapping interface keeps the result
    convenient for API adapters while attribute access remains the primary API.
    """

    probability: float
    level: RiskLevel
    trend: Trend
    evidence: tuple[str, ...]
    recheck_window_hours: tuple[int, int]
    confidence: float
    horizon_hours: int
    as_of: datetime | None = None
    feature_values: Mapping[str, float] = field(default_factory=dict)
    model_version: str = "heuristic-region-risk-v1"

    @property
    def risk_probability(self) -> float:
        return self.probability

    @property
    def risk_level(self) -> RiskLevel:
        return self.level

    @property
    def basis(self) -> tuple[str, ...]:
        return self.evidence

    @property
    def recheck_window(self) -> tuple[datetime, datetime] | tuple[int, int]:
        if self.as_of is None:
            return self.recheck_window_hours
        start, end = self.recheck_window_hours
        return (self.as_of + timedelta(hours=start), self.as_of + timedelta(hours=end))

    @property
    def suggested_recheck_time_window(self) -> tuple[datetime, datetime] | tuple[int, int]:
        return self.recheck_window

    @property
    def recommended_recheck_window(self) -> tuple[datetime, datetime] | tuple[int, int]:
        """Alias used by API adapters that call the window a recommendation."""

        return self.recheck_window

    @property
    def recheck_time_window_hours(self) -> tuple[int, int]:
        return self.recheck_window_hours

    def to_dict(self) -> dict[str, Any]:
        """Return JSON-friendly output without exposing internal tuples."""

        window = self.recheck_window
        return {
            "probability": self.probability,
            "risk_probability": self.probability,
            "level": self.level,
            "risk_level": self.level,
            "trend": self.trend,
            "evidence": list(self.evidence),
            "recheck_window_hours": {
                "earliest": self.recheck_window_hours[0],
                "latest": self.recheck_window_hours[1],
            },
            "recheck_window": [
                value.isoformat() if isinstance(value, datetime) else value
                for value in window
            ],
            "suggested_recheck_time_window": [
                value.isoformat() if isinstance(value, datetime) else value
                for value in window
            ],
            "recommended_recheck_window": [
                value.isoformat() if isinstance(value, datetime) else value
                for value in window
            ],
            "confidence": self.confidence,
            "horizon_hours": self.horizon_hours,
            "as_of": self.as_of.isoformat() if self.as_of else None,
            "feature_values": dict(self.feature_values),
            "model_version": self.model_version,
        }

    def __getitem__(self, key: str) -> Any:
        return self.to_dict()[key]

    def __iter__(self) -> Iterator[str]:
        return iter(self.to_dict())

    def __len__(self) -> int:
        return len(self.to_dict())


@dataclass(frozen=True, slots=True)
class RiskThresholds:
    """Thresholds kept explicit so an experiment can freeze them."""

    low_max: float = 0.33
    medium_max: float = 0.66
    rising_delta: float = 0.08

    def __post_init__(self) -> None:
        if not 0 <= self.low_max < self.medium_max <= 1:
            raise ValueError("risk thresholds must satisfy 0 <= low < medium <= 1")
        if self.rising_delta <= 0:
            raise ValueError("rising_delta must be positive")


def _observation_mapping(item: RegionObservation | Mapping[str, Any]) -> Mapping[str, Any]:
    if isinstance(item, RegionObservation):
        return item.as_mapping()
    if isinstance(item, Mapping):
        return item
    raise TypeError("history items must be mappings or RegionObservation instances")


def _visual_score(item: Mapping[str, Any]) -> float | None:
    explicit = _first(
        item,
        "visual_risk",
        "risk_score",
        "disease_probability",
        "disease_score",
        "anomaly_score",
        "severity",
        "stress_ratio",
    )
    score = _normalise_score(explicit)
    if score is not None:
        return score

    detected = _first(item, "disease_detected", "disease_present", "stress_detected")
    if detected is not None:
        return 1.0 if bool(detected) else 0.0

    detections = _first(item, "disease_detections", "detections")
    if isinstance(detections, Sequence) and not isinstance(detections, (str, bytes)):
        return 0.8 if len(detections) else 0.0

    vigor = _number(_first(item, "vigor_level", "vigor"))
    if vigor is not None:
        # The existing Analysis contract uses vigor 1..5. Lower vigor is a
        # weak stress proxy only when no explicit disease signal is provided.
        return _clamp((5.0 - _clamp(vigor, 1.0, 5.0)) / 4.0)
    return None


def _quality_score(item: Mapping[str, Any]) -> float | None:
    quality = _as_mapping(item.get("quality"))
    if not quality:
        quality = _as_mapping(item.get("quality_features"))
    explicit = _first(item, "quality_score", "image_quality", "quality")
    direct = _normalise_score(explicit)
    if direct is not None and not isinstance(explicit, Mapping):
        return direct
    if isinstance(explicit, str):
        return {"good": 1.0, "fair": 0.65, "poor": 0.25, "unknown": 0.5}.get(
            explicit.lower(),
        )
    if not quality:
        quality = _as_mapping(_first(item, "sensor_quality"))

    values: list[float] = []
    for key in ("score", "image", "image_score", "quality_score", "sharpness"):
        value = _normalise_score(quality.get(key))
        if value is not None:
            values.append(value)
    for key in ("occlusion_ratio", "blur_ratio", "position_error_ratio"):
        value = _normalise_score(quality.get(key))
        if value is not None:
            values.append(1.0 - value)
    error_m = _number(quality.get("position_error_m"))
    if error_m is not None:
        values.append(_clamp(1.0 - error_m / 2.0))
    if values:
        return sum(values) / len(values)
    return None


def _environment_score(values: Mapping[str, Any]) -> float | None:
    """Map common environment measurements to a generic disease-favourability score."""

    explicit = _normalise_score(
        values.get("environment_risk", values.get("environment_score", values.get("favorability_score")))
    )
    if explicit is not None:
        return explicit

    components: list[float] = []
    for key in ("humidity_pct", "relative_humidity", "humidity"):
        value = _number(values.get(key))
        if value is not None:
            components.append(_clamp((value - 60.0) / 35.0))
            break
    for key, scale in (("leaf_wetness_hours", 12.0), ("rain_24h_mm", 30.0), ("rain_7d_mm", 80.0), ("rain_mm", 20.0)):
        value = _number(values.get(key))
        if value is not None:
            components.append(_clamp(value / scale))
    soil = _number(values.get("soil_moisture_pct"))
    if soil is not None:
        components.append(_clamp((soil - 50.0) / 40.0))
    return sum(components) / len(components) if components else None


def _merge_environment(
    history: Sequence[Mapping[str, Any]],
    environment: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for item in history:
        merged.update(_as_mapping(item.get("environment")))
        merged.update(_as_mapping(item.get("environment_features")))
    if isinstance(environment, Mapping):
        merged.update(environment)
    elif environment is not None:
        for item in environment:
            merged.update(_as_mapping(item))
    return merged


def _merge_quality(
    history: Sequence[Mapping[str, Any]],
    quality: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None,
) -> dict[str, Any]:
    merged: dict[str, Any] = {}
    for item in history:
        merged.update(_as_mapping(item.get("quality")))
        merged.update(_as_mapping(item.get("quality_features")))
    if isinstance(quality, Mapping):
        merged.update(quality)
    elif quality is not None:
        for item in quality:
            merged.update(_as_mapping(item))
    return merged


def _trend(scores: Sequence[float], threshold: float) -> tuple[Trend, float]:
    if len(scores) < 2:
        return "unknown", 0.0
    delta = scores[-1] - scores[0]
    if delta >= threshold:
        return "rising", delta
    if delta <= -threshold:
        return "falling", delta
    return "stable", delta


def _level(probability: float, *, has_evidence: bool, thresholds: RiskThresholds) -> RiskLevel:
    if not has_evidence:
        return "unknown"
    if probability < thresholds.low_max:
        return "low"
    if probability < thresholds.medium_max:
        return "medium"
    return "high"


def _recheck_window(level: RiskLevel, trend: Trend, confidence: float, horizon_hours: int) -> tuple[int, int]:
    # Short windows are intentionally capped by the requested prediction
    # horizon; a longer horizon still leaves enough room for a follow-up.
    if level == "high" or trend == "rising":
        earliest, latest = 6, 24
    elif level == "medium":
        earliest, latest = 24, 48
    elif level == "low":
        earliest, latest = 48, 96
    else:
        earliest, latest = 12, 24
    latest = min(latest, max(1, horizon_hours))
    earliest = min(earliest, latest)
    # Weak evidence should be checked soon enough to recover missing data.
    if confidence < 0.55:
        earliest = min(earliest, 12)
        latest = min(max(earliest, latest), max(12, horizon_hours))
    return earliest, latest


def predict_region_risk(
    history: Iterable[RegionObservation | Mapping[str, Any]] | None = None,
    environment: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    quality: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
    *,
    observations: Iterable[RegionObservation | Mapping[str, Any]] | None = None,
    horizon_hours: int = 48,
    as_of: datetime | date | str | None = None,
    thresholds: RiskThresholds | None = None,
    model_version: str = "heuristic-region-risk-v1",
) -> RiskPrediction:
    """Predict risk for one observation region using interpretable features.

    ``history`` is ordered from oldest to newest when timestamps are absent. Each
    item may contain a visual risk signal (``risk_score``, ``disease_score``,
    ``severity`` or ``disease_detected``), and optional nested ``environment``
    and ``quality`` mappings. ``environment`` and ``quality`` arguments provide
    the latest region-level aggregates and override nested values.

    The calculation is a frozen baseline, not a fitted disease model:

    * recent visual signal contributes up to 55%;
    * positive/negative temporal change contributes up to 20%;
    * common environmental favourability features contribute up to 25%;
    * quality gates confidence and shrinks the estimate toward 0.5.
    """

    if horizon_hours <= 0:
        raise ValueError("horizon_hours must be positive")
    if observations is not None:
        if history is not None:
            raise TypeError("pass either history or observations, not both")
        history = observations

    raw_items = list(history or ())
    items = [_observation_mapping(item) for item in raw_items]
    # If timestamps are available, sort a copy so a caller cannot accidentally
    # calculate a trend backwards after merging data from multiple sources.
    timestamped = [(_parse_datetime(_first(item, "observed_at", "captured_at", "timestamp", "time")), item) for item in items]
    if timestamped and all(timestamp is not None for timestamp, _ in timestamped):
        items = [item for _, item in sorted(timestamped, key=lambda pair: pair[0])]  # type: ignore[arg-type]

    scores = [score for item in items if (score := _visual_score(item)) is not None]
    recent = scores[-1] if scores else None
    average = sum(scores) / len(scores) if scores else None
    trend, delta = _trend(scores, (thresholds or RiskThresholds()).rising_delta)
    trend_component = _clamp(0.5 + delta * 1.25) if len(scores) >= 2 else None

    env_values = _merge_environment(items, environment)
    environment_component = _environment_score(env_values)

    quality_values = [_quality_score(item) for item in items]
    quality_values = [value for value in quality_values if value is not None]
    aggregate_quality = _quality_score({"quality": _merge_quality(items, quality)})
    if aggregate_quality is None and quality_values:
        aggregate_quality = sum(quality_values) / len(quality_values)
    if aggregate_quality is None:
        # Missing quality is uncertainty, not a perfect image.
        aggregate_quality = 0.65

    components: list[tuple[float, float]] = []
    if recent is not None:
        components.append((recent, 0.55))
    if trend_component is not None:
        components.append((trend_component, 0.20))
    if environment_component is not None:
        components.append((environment_component, 0.25))
    if components:
        raw_probability = sum(value * weight for value, weight in components) / sum(weight for _, weight in components)
    else:
        raw_probability = 0.5

    # Quality is a reliability gate. A poor image/location record should not
    # make an uncertain estimate look confidently low or high.
    quality_gate = 0.35 + 0.65 * _clamp(aggregate_quality)
    probability = _clamp(0.5 + (raw_probability - 0.5) * quality_gate)
    probability = round(probability, 4)

    has_evidence = bool(scores or environment_component is not None)
    coverage = min(len(scores) / 3.0, 1.0) if scores else 0.0
    if environment_component is not None:
        coverage = max(coverage, 0.35)
    confidence = _clamp(coverage * (0.55 + 0.45 * _clamp(aggregate_quality)))
    if len(scores) >= 2:
        confidence = _clamp(confidence + 0.1)
    confidence = round(confidence, 4)

    threshold_values = thresholds or RiskThresholds()
    level = _level(probability, has_evidence=has_evidence, thresholds=threshold_values)
    window = _recheck_window(level, trend, confidence, horizon_hours)
    parsed_as_of = _parse_datetime(as_of)

    evidence: list[str] = []
    if recent is not None:
        evidence.append(f"recent_visual_risk={recent:.2f}")
    else:
        evidence.append("visual_evidence=missing")
    if len(scores) >= 2:
        evidence.append(f"temporal_trend={trend} ({delta:+.2f})")
    else:
        evidence.append("temporal_trend=unknown (fewer than 2 valid observations)")
    if environment_component is not None:
        evidence.append(f"environment_favourability={environment_component:.2f}")
    else:
        evidence.append("environment_evidence=missing")
    evidence.append(f"quality_gate={aggregate_quality:.2f}")
    if aggregate_quality < 0.5:
        evidence.append("quality_gate=low; collect a clearer or better-localised observation")
    if not has_evidence:
        evidence.append("insufficient evidence; schedule a short recheck")

    feature_values: dict[str, float] = {
        "recent_visual_risk": round(recent, 4) if recent is not None else 0.0,
        "quality_score": round(_clamp(aggregate_quality), 4),
    }
    if average is not None:
        feature_values["historical_visual_risk_mean"] = round(average, 4)
    if trend_component is not None:
        feature_values["trend_component"] = round(trend_component, 4)
    if environment_component is not None:
        feature_values["environment_favourability"] = round(environment_component, 4)

    return RiskPrediction(
        probability=probability,
        level=level,
        trend=trend,
        evidence=tuple(evidence),
        recheck_window_hours=window,
        confidence=confidence,
        horizon_hours=horizon_hours,
        as_of=parsed_as_of,
        feature_values=feature_values,
        model_version=model_version,
    )


def predict_risk(*args: Any, **kwargs: Any) -> RiskPrediction:
    """Short alias for integrations that use the generic predictor name."""

    return predict_region_risk(*args, **kwargs)


__all__ = [
    "RegionObservation",
    "RiskPrediction",
    "RiskThresholds",
    "predict_region_risk",
    "predict_risk",
]
