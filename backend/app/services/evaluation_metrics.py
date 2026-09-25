"""风险预测评估指标（纯函数，不读写数据库）。

申报书 9.2 的主要指标：PR-AUC（类别不平衡下的排序能力）、Brier 分数（概率与结果的一致程度）、
固定误报负担下的召回率、事件级提前量（同时报告未被预警的事件）。

标签口径（与随访状态机、决策 D10 一致）：
- ``confirmed_positive`` → 1，``confirmed_negative`` → 0；
- ``intervened`` 是删失：处置改变了结局，既不算阳性也不算阴性，只计数；
- ``insufficient`` / ``unknown`` / ``pending`` / 没有随访：结局未知，不进分母，只计数。

Brier 对未校准的分数不公平。校准时按时间先后拆分：前段拟合等渗回归、后段评估，
避免同一批数据既拟合又评估。
"""
from __future__ import annotations

import statistics
from collections import Counter
from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

STATUS_LABEL = {"confirmed_positive": 1, "confirmed_negative": 0}
CENSORED_STATUSES = frozenset({"intervened"})


def label_of(status: str | None) -> int | None:
    """随访状态 → 0/1 标签；删失与未知返回 None。"""
    return STATUS_LABEL.get(status or "")


def _check(scores: Sequence[float], labels: Sequence[int]) -> None:
    if len(scores) != len(labels):
        raise ValueError("scores 与 labels 长度不一致")
    if any(label not in (0, 1) for label in labels):
        raise ValueError("labels 只能是 0/1")


def average_precision(scores: Sequence[float], labels: Sequence[int]) -> float | None:
    """PR 曲线下面积（average precision，与 sklearn 同定义：按不同阈值累加 ΔRecall × Precision）。

    没有阳性样本时无定义，返回 None。并列分数作为同一阈值处理，不依赖输入顺序。
    """
    _check(scores, labels)
    positives = sum(labels)
    if positives == 0:
        return None
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    ap = tp = fp = 0.0
    prev_recall = 0.0
    i = 0
    while i < len(order):
        threshold = scores[order[i]]
        while i < len(order) and scores[order[i]] == threshold:
            if labels[order[i]]:
                tp += 1
            else:
                fp += 1
            i += 1
        recall = tp / positives
        ap += (recall - prev_recall) * (tp / (tp + fp))
        prev_recall = recall
    return round(ap, 6)


def brier_score(probs: Sequence[float], labels: Sequence[int]) -> float | None:
    _check(probs, labels)
    if not probs:
        return None
    return round(sum((p - y) ** 2 for p, y in zip(probs, labels)) / len(probs), 6)


@dataclass(frozen=True, slots=True)
class IsotonicCalibrator:
    """等渗回归（PAV）：单调不减的阶梯函数，按分数把原始分映射为校准概率。"""

    upper_bounds: tuple[float, ...]  # 每一阶的分数上界（升序）
    values: tuple[float, ...]        # 每一阶的校准概率

    @classmethod
    def fit(cls, scores: Sequence[float], labels: Sequence[int]) -> "IsotonicCalibrator":
        _check(scores, labels)
        if not scores:
            raise ValueError("至少需要一个样本才能校准")
        grouped: dict[float, list[int]] = {}
        for s, y in zip(scores, labels):
            grouped.setdefault(float(s), []).append(y)
        # 每个块：[分数上界, 加权均值, 权重]
        blocks: list[list[float]] = []
        for s in sorted(grouped):
            ys = grouped[s]
            blocks.append([s, sum(ys) / len(ys), float(len(ys))])
            while len(blocks) >= 2 and blocks[-2][1] > blocks[-1][1]:
                upper, mean, weight = blocks.pop()
                prev = blocks[-1]
                total = prev[2] + weight
                prev[1] = (prev[1] * prev[2] + mean * weight) / total
                prev[2] = total
                prev[0] = upper
        return cls(tuple(b[0] for b in blocks), tuple(b[1] for b in blocks))

    def predict(self, score: float) -> float:
        for upper, value in zip(self.upper_bounds, self.values):
            if score <= upper:
                return value
        return self.values[-1]


def reliability_bins(probs: Sequence[float], labels: Sequence[int], n_bins: int = 10) -> list[dict[str, Any]]:
    """可靠性图数据：按预测概率等宽分箱，比较平均预测与实际阳性率。"""
    _check(probs, labels)
    bins: dict[int, list[tuple[float, int]]] = {}
    for p, y in zip(probs, labels):
        index = min(int(p * n_bins), n_bins - 1)
        bins.setdefault(index, []).append((p, y))
    return [
        {
            "range": [round(i / n_bins, 3), round((i + 1) / n_bins, 3)],
            "count": len(items),
            "mean_prob": round(sum(p for p, _ in items) / len(items), 4),
            "positive_rate": round(sum(y for _, y in items) / len(items), 4),
        }
        for i, items in sorted(bins.items())
    ]


def recall_at_fp_budget(
    scores: Sequence[float],
    labels: Sequence[int],
    units: Sequence[Hashable],
    fp_per_unit: float,
) -> dict[str, Any]:
    """在「每个单位（如地块·日）误报不超过 fp_per_unit 条」的约束下，能达到的最高召回率。

    申报书用「相同误报负担下的事件召回率」比较模型；单位数取全部被评估记录涉及的单位。
    """
    _check(scores, labels)
    positives = sum(labels)
    n_units = len(set(units))
    result: dict[str, Any] = {
        "fp_per_unit_budget": fp_per_unit, "units": n_units,
        "recall": None, "threshold": None, "fp_per_unit": None,
    }
    if positives == 0 or n_units == 0:
        return result
    best_recall, best = 0.0, (None, 0.0)
    order = sorted(range(len(scores)), key=lambda i: -scores[i])
    tp = fp = 0
    i = 0
    while i < len(order):
        threshold = scores[order[i]]
        while i < len(order) and scores[order[i]] == threshold:
            tp += labels[order[i]]
            fp += 1 - labels[order[i]]
            i += 1
        rate = fp / n_units
        if rate > fp_per_unit:
            break
        if tp / positives > best_recall:  # 同召回取最高阈值（误报最少）
            best_recall, best = tp / positives, (threshold, rate)
    result.update(
        recall=round(best_recall, 6),
        threshold=best[0],
        fp_per_unit=round(best[1], 6) if best[0] is not None else None,
    )
    return result


@dataclass(frozen=True, slots=True)
class WindowPrediction:
    region: str
    forecast_start: datetime
    forecast_end: datetime
    probability: float


def event_lead_times(
    events: Sequence[tuple[str, datetime]],
    predictions: Sequence[WindowPrediction],
    threshold: float,
) -> dict[str, Any]:
    """事件级提前量：每个事件取同一区域、窗口覆盖事件时间、且概率达到阈值的最早预警。

    未被预警的事件单独计数（申报书 9.2：不能只挑成功案例求平均）。
    """
    by_region: dict[str, list[WindowPrediction]] = {}
    for p in predictions:
        by_region.setdefault(p.region, []).append(p)
    leads: list[float] = []
    missed = 0
    for region, event_at in events:
        starts = [
            p.forecast_start for p in by_region.get(region, [])
            if p.probability >= threshold and p.forecast_start < event_at <= p.forecast_end
        ]
        if starts:
            leads.append((event_at - min(starts)).total_seconds() / 3600)
        else:
            missed += 1
    total = len(events)
    return {
        "threshold": threshold,
        "events": total,
        "warned": len(leads),
        "missed": missed,
        "missed_rate": round(missed / total, 4) if total else None,
        "median_lead_hours": round(statistics.median(leads), 2) if leads else None,
        "min_lead_hours": round(min(leads), 2) if leads else None,
        "max_lead_hours": round(max(leads), 2) if leads else None,
    }


@dataclass(frozen=True, slots=True)
class LabeledPrediction:
    """一条已随访（或未随访）的预测，供汇总评估。"""

    probability: float
    status: str | None
    unit: Hashable
    order_key: Any  # 排序依据（通常是 forecast_start），用于按时间拆分校准


def evaluate_predictions(
    records: Sequence[LabeledPrediction],
    *,
    fp_per_unit: float = 2.0,
    calibrate: bool = False,
    n_bins: int = 10,
) -> dict[str, Any]:
    """汇总评估：状态计数 → 可评估样本 → PR-AUC / Brier / 可靠性 / 固定误报召回率（可选时间拆分校准）。"""
    status_counts = Counter(r.status or "no_follow_up" for r in records)
    evaluable = [r for r in records if label_of(r.status) is not None]
    probs = [r.probability for r in evaluable]
    labels = [label_of(r.status) for r in evaluable]  # type: ignore[misc]
    report: dict[str, Any] = {
        "status_counts": dict(sorted(status_counts.items())),
        "censored": sum(status_counts[s] for s in CENSORED_STATUSES),
        "evaluable": len(evaluable),
        "positives": sum(labels),
        "prevalence": round(sum(labels) / len(labels), 4) if labels else None,
        "pr_auc": average_precision(probs, labels) if labels else None,
        "brier": brier_score(probs, labels),
        "reliability": reliability_bins(probs, labels, n_bins) if labels else [],
        "recall_at_fp": recall_at_fp_budget(probs, labels, [r.unit for r in evaluable], fp_per_unit),
    }
    if calibrate:
        report["calibration"] = _time_split_calibration(evaluable)
    return report


def _time_split_calibration(evaluable: Sequence[LabeledPrediction]) -> dict[str, Any]:
    """前半段（按 order_key）拟合等渗校准，后半段比较校准前后的 Brier。"""
    ordered = sorted(evaluable, key=lambda r: r.order_key)
    half = len(ordered) // 2
    fit, test = ordered[:half], ordered[half:]
    if not fit or not test:
        return {"status": "insufficient", "n_fit": len(fit), "n_eval": len(test)}
    calibrator = IsotonicCalibrator.fit([r.probability for r in fit], [label_of(r.status) for r in fit])  # type: ignore[misc]
    test_labels = [label_of(r.status) for r in test]
    raw = [r.probability for r in test]
    calibrated = [calibrator.predict(p) for p in raw]
    return {
        "status": "ok",
        "method": "isotonic, time-split 50/50",
        "n_fit": len(fit),
        "n_eval": len(test),
        "brier_raw": brier_score(raw, test_labels),  # type: ignore[arg-type]
        "brier_calibrated": brier_score(calibrated, test_labels),  # type: ignore[arg-type]
        "pr_auc_eval": average_precision(raw, test_labels) if sum(test_labels) else None,  # type: ignore[arg-type]
    }
