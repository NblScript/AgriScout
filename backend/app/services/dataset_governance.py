"""数据集冻结与模型评估门禁。

该模块把人工标注、采样点和当时的分析结论组成可复现的 NDJSON 快照。
冻结之后快照字段只读；照片依然通过 ``photo_url`` 引用内容寻址存储。

计划 0007 P1-7：冻结时按「地块 + 田间日期」整组划分训练 / 验证 / 测试，划分参数写进快照摘要；
模型评估提交逐条预测，由平台对照快照的测试组重算指标，审批只认平台算出的数（决策 D24）。
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutil import field_date
from app.models import Analysis, Annotation, CapturePoint, DatasetVersion, ModelEvaluation, Patrol
from app.services.evaluation_metrics import average_precision


SNAPSHOT_SCHEMA = "agriscout.dataset.v2"
SPLIT_METHOD = "group-shuffle-v1"
SPLIT_NAMES = ("train", "val", "test")
GROUP_BY = ("field_date", "field")
# 病害目标的默认阳性标签与不参与评估的标签；数据集 label_schema 可用 positive_labels / ignore_labels 覆盖
DEFAULT_POSITIVE_LABELS = ("suspected_disease", "downy_mildew_early", "downy_mildew_symptomatic")
DEFAULT_IGNORE_LABELS = ("other",)
RECOMPUTE_METHOD = "platform-recompute-v1"


@dataclass(frozen=True)
class SplitSpec:
    """分组划分参数：同组样本整组进同一份，组按 sha256(种子|组键) 排序后依次填满测试、验证，其余为训练。"""

    seed: int = 0
    group_by: str = "field_date"
    ratios: dict[str, float] = field(default_factory=lambda: {"train": 0.7, "val": 0.15, "test": 0.15})

    def __post_init__(self) -> None:
        if self.group_by not in GROUP_BY:
            raise ValueError(f"group_by 只能是 {'、'.join(GROUP_BY)}")
        if set(self.ratios) != set(SPLIT_NAMES):
            raise ValueError("ratios 必须正好给出 train、val、test 三份")
        values = [self.ratios[name] for name in SPLIT_NAMES]
        if any(not isinstance(v, (int, float)) or isinstance(v, bool) or not 0 <= v <= 1 for v in values):
            raise ValueError("ratios 每一份都必须在 0 到 1 之间")
        if abs(sum(values) - 1) > 1e-6:
            raise ValueError("ratios 三份之和必须为 1")
        if self.ratios["test"] <= 0:
            raise ValueError("测试组比例必须大于 0：模型发布只认测试组")


@dataclass(frozen=True)
class DatasetSnapshot:
    """构建但尚未写入数据库的确定性快照。"""

    ndjson: str
    sha256: str
    row_count: int
    summary: dict[str, Any]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _filter_date(source_filter: dict[str, Any], key: str) -> date | None:
    raw = source_filter.get(key)
    if raw in (None, ""):
        return None
    try:
        return date.fromisoformat(str(raw))
    except ValueError as exc:
        raise ValueError(f"source_filter.{key} 必须是 YYYY-MM-DD 格式的田间日期") from exc


def _source_filter_clause(stmt, source_filter: dict[str, Any] | None):
    source_filter = source_filter or {}
    patrol_id = source_filter.get("patrol_id")
    if patrol_id is not None:
        stmt = stmt.where(Annotation.patrol_id == int(patrol_id))
    field_id = source_filter.get("field_id")
    if field_id is not None:
        stmt = stmt.where(Patrol.field_id == int(field_id))
    labels = source_filter.get("labels")
    if labels:
        if not isinstance(labels, list) or not all(isinstance(label, str) for label in labels):
            raise ValueError("source_filter.labels 必须是字符串列表")
        stmt = stmt.where(Annotation.label.in_(labels))
    annotator = source_filter.get("annotator_name")
    if annotator:
        stmt = stmt.where(Annotation.annotator_name == str(annotator))
    min_id = source_filter.get("min_annotation_id")
    if min_id is not None:
        stmt = stmt.where(Annotation.id >= int(min_id))
    max_id = source_filter.get("max_annotation_id")
    if max_id is not None:
        stmt = stmt.where(Annotation.id <= int(max_id))
    return stmt


def _label_list(label_schema: dict[str, Any], key: str, default: Sequence[str]) -> list[str]:
    value = label_schema.get(key, list(default))
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"label_schema.{key} 必须是字符串列表")
    return sorted(set(value))


def _evaluation_labels(label_schema: dict[str, Any] | None) -> dict[str, list[str]]:
    """冻结时写定的二分类口径：哪些标签算阳性、哪些标签不参与评估。"""
    label_schema = label_schema or {}
    positive = _label_list(label_schema, "positive_labels", DEFAULT_POSITIVE_LABELS)
    ignore = _label_list(label_schema, "ignore_labels", DEFAULT_IGNORE_LABELS)
    if not positive:
        raise ValueError("label_schema.positive_labels 不能为空")
    if set(positive) & set(ignore):
        raise ValueError("同一标签不能既算阳性又不参与评估")
    return {"positive_labels": positive, "ignore_labels": ignore}


def _group_key(field_id: int, day: date, group_by: str) -> str:
    return f"{field_id}:{day.isoformat()}" if group_by == "field_date" else str(field_id)


def assign_splits(group_sizes: dict[str, int], spec: SplitSpec) -> dict[str, str]:
    """把各组分到 train / val / test（纯函数，结果只取决于组键、组大小和划分参数）。

    组按 sha256(种子|组键) 排序；依次先填测试组、再填验证组，直到各自行数达到目标比例，其余为训练组。
    比例大于 0 的份至少分到一组（组数够的话），所以只有两三组时也有测试组。
    """
    total = sum(group_sizes.values())
    targets = {name: spec.ratios[name] * total for name in ("test", "val")}
    counts = dict.fromkeys(SPLIT_NAMES, 0)
    order = sorted(group_sizes, key=lambda key: (hashlib.sha256(f"{spec.seed}|{key}".encode()).hexdigest(), key))
    assigned: dict[str, str] = {}
    for key in order:
        name = next((n for n in ("test", "val") if counts[n] < targets[n]), "train")
        assigned[key] = name
        counts[name] += group_sizes[key]
    return assigned


def build_dataset_snapshot(
    db: Session,
    dataset: DatasetVersion,
    *,
    source_filter: dict[str, Any] | None = None,
    split: SplitSpec | None = None,
) -> DatasetSnapshot:
    """从当前数据库构建排序稳定的 NDJSON 快照。

    每行对应一条人工标注，并带上照片 URL、空间/时间采样信息、机器分析结果和所属划分。
    ``source_filter`` 缺省使用数据集上保存的过滤条件；``split`` 缺省为种子 0、按「地块 + 田间日期」分组。
    """
    filter_value = dataset.source_filter if source_filter is None else source_filter
    filter_value = filter_value or {}
    split = split or SplitSpec()
    evaluation_labels = _evaluation_labels(dataset.label_schema)
    date_from = _filter_date(filter_value, "date_from")
    date_to = _filter_date(filter_value, "date_to")
    stmt = (
        select(Annotation, CapturePoint, Analysis, Patrol.field_id)
        .join(CapturePoint, Annotation.capture_point_id == CapturePoint.id)
        .join(Patrol, Annotation.patrol_id == Patrol.id)
        .outerjoin(Analysis, Analysis.capture_point_id == CapturePoint.id)
        .order_by(Annotation.patrol_id, CapturePoint.seq, Annotation.id)
    )
    stmt = _source_filter_clause(stmt, filter_value)

    rows: list[dict[str, Any]] = []
    for ann, point, analysis, field_id in db.execute(stmt):
        day = field_date(point.captured_at)
        if (date_from and day < date_from) or (date_to and day > date_to):
            continue
        rows.append(
            {
                "schema_version": SNAPSHOT_SCHEMA,
                "annotation_id": ann.id,
                "patrol_id": ann.patrol_id,
                "capture_point_id": point.id,
                "field_id": field_id,
                "field_date": day.isoformat(),
                "observation_key": point.observation_key,
                "group": _group_key(field_id, day, split.group_by),
                "label": ann.label,
                "bbox": ann.bbox,
                "note": ann.note,
                "annotator_name": ann.annotator_name,
                "reviewed_at": _iso(ann.updated_at),
                # 照片仍是 URL；快照不复制照片字节。
                "photo_url": point.photo_url,
                "point": {
                    "seq": point.seq,
                    "distance_m": point.distance_m,
                    "lng": point.lng,
                    "lat": point.lat,
                    "captured_at": _iso(point.captured_at),
                },
                "analysis": (
                    {
                        "analyzer_version": analysis.analyzer_version,
                        "growth_stage": analysis.growth_stage,
                        "vigor_level": analysis.vigor_level,
                        "ndvi": analysis.ndvi,
                        "disease_detections": analysis.disease_detections,
                        "risk_score": analysis.risk_score,
                        "detail": analysis.detail,
                        "analyzed_at": _iso(analysis.analyzed_at),
                    }
                    if analysis
                    else None
                ),
            }
        )

    assigned = assign_splits(Counter(row["group"] for row in rows), split)
    for row in rows:
        row["split"] = assigned[row["group"]]

    lines = [json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for row in rows]
    ndjson = "\n".join(lines) + ("\n" if lines else "")
    counts = Counter(row["label"] for row in rows)
    with_analysis = sum(row["analysis"] is not None for row in rows)
    summary = {
        "schema_version": SNAPSHOT_SCHEMA,
        "row_count": len(rows),
        "labels": dict(sorted(counts.items())),
        "with_analysis": with_analysis,
        "without_analysis": len(rows) - with_analysis,
        "source_filter": filter_value,
        "split": {
            "method": SPLIT_METHOD,
            "group_by": split.group_by,
            "seed": split.seed,
            "ratios": {name: split.ratios[name] for name in SPLIT_NAMES},
            "counts": {name: sum(row["split"] == name for row in rows) for name in SPLIT_NAMES},
            "groups": {name: sorted(k for k, v in assigned.items() if v == name) for name in SPLIT_NAMES},
            "labels": {
                name: dict(sorted(Counter(row["label"] for row in rows if row["split"] == name).items()))
                for name in SPLIT_NAMES
            },
        },
        "evaluation": evaluation_labels,
    }
    return DatasetSnapshot(
        ndjson=ndjson,
        sha256=hashlib.sha256(ndjson.encode("utf-8")).hexdigest(),
        row_count=len(rows),
        summary=summary,
    )


def freeze_dataset_version(
    db: Session,
    dataset: DatasetVersion,
    *,
    split: SplitSpec | None = None,
    now: datetime | None = None,
) -> DatasetSnapshot:
    """构建并冻结数据集；无标注样本或重复修改会失败。"""
    if dataset.status == "frozen":
        raise ValueError("数据集已冻结，不能重新生成快照")
    if dataset.status not in {"draft", "candidate"}:
        raise ValueError(f"数据集状态不允许冻结: {dataset.status}")
    snapshot = build_dataset_snapshot(db, dataset, split=split)
    if snapshot.row_count <= 0:
        raise ValueError("不能冻结空数据集：请先完成至少一条人工标注")
    dataset.snapshot_ndjson = snapshot.ndjson
    dataset.snapshot_sha256 = snapshot.sha256
    dataset.snapshot_summary = snapshot.summary
    dataset.row_count = snapshot.row_count
    dataset.status = "frozen"
    dataset.frozen_at = now or datetime.now(timezone.utc)
    db.flush()
    return snapshot


def _ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 6) if denominator else None


def _format_ids(ids: set[int]) -> str:
    shown = sorted(ids)[:5]
    return "、".join(str(i) for i in shown) + (f" 等 {len(ids)} 条" if len(ids) > len(shown) else "")


def recompute_metrics(
    dataset: DatasetVersion,
    *,
    split: str,
    predictions: Sequence[dict[str, Any]],
    threshold: float,
) -> dict[str, Any]:
    """对照冻结快照里 ``split`` 组的标注，重算逐条预测的指标（纯函数，不写库）。

    预测必须正好覆盖该组全部可评估样本（不参与评估的标签除外），不能缺、不能多、不能重复。
    分数 ≥ 阈值算预测阳性；pr_auc 用与 sklearn 同定义的 average precision。
    """
    summary = dataset.snapshot_summary or {}
    if dataset.status != "frozen" or not dataset.snapshot_ndjson:
        raise ValueError("模型评估必须使用已冻结且有快照内容的数据集")
    if "split" not in summary or "evaluation" not in summary:
        raise ValueError("该数据集冻结时还没有分组划分，不能用于评估：请按新规则重新冻结一个版本")
    if not 0 <= threshold <= 1:
        raise ValueError("threshold 必须在 0 到 1 之间")
    positive = set(summary["evaluation"]["positive_labels"])
    ignore = set(summary["evaluation"]["ignore_labels"])
    rows = [json.loads(line) for line in dataset.snapshot_ndjson.splitlines() if line]
    expected = {row["annotation_id"]: row["label"] for row in rows if row["split"] == split and row["label"] not in ignore}
    if not expected:
        raise ValueError(f"快照的 {split} 组没有可评估样本")

    scores: dict[int, float] = {}
    for item in predictions:
        annotation_id, score = item.get("annotation_id"), item.get("score")
        if not isinstance(annotation_id, int) or isinstance(annotation_id, bool):
            raise ValueError("predictions 每一条都要有整数 annotation_id")
        if not isinstance(score, (int, float)) or isinstance(score, bool) or not math.isfinite(score) or not 0 <= score <= 1:
            raise ValueError(f"标注 {annotation_id} 的 score 必须是 0 到 1 之间的有限数值")
        if annotation_id in scores:
            raise ValueError(f"标注 {annotation_id} 的预测重复提交")
        scores[annotation_id] = float(score)
    missing, extra = set(expected) - set(scores), set(scores) - set(expected)
    if missing:
        raise ValueError(f"预测缺少快照 {split} 组的样本：标注 {_format_ids(missing)}")
    if extra:
        raise ValueError(f"预测里有不属于快照 {split} 组可评估样本的标注：{_format_ids(extra)}")

    ids = sorted(expected)
    labels = [int(expected[i] in positive) for i in ids]
    values = [scores[i] for i in ids]
    tp = sum(1 for v, y in zip(values, labels) if y and v >= threshold)
    fp = sum(1 for v, y in zip(values, labels) if not y and v >= threshold)
    fn = sum(labels) - tp
    tn = len(ids) - sum(labels) - fp
    precision, recall = _ratio(tp, tp + fp), _ratio(tp, tp + fn)
    if precision is None or recall is None:
        f1 = None
    else:
        f1 = round(2 * precision * recall / (precision + recall), 6) if precision + recall else 0.0
    return {
        "method": RECOMPUTE_METHOD,
        "split": split,
        "threshold": threshold,
        "snapshot_sha256": dataset.snapshot_sha256,
        "positive_labels": sorted(positive),
        "n": len(ids),
        "positives": sum(labels),
        "negatives": len(ids) - sum(labels),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "pr_auc": average_precision(values, labels),
    }


def validate_evaluation_gate(db: Session, evaluation: ModelEvaluation) -> DatasetVersion:
    """验证模型发布前置条件，失败抛出 ValueError/LookupError；通过时刷新 ``platform_metrics``。"""
    if evaluation.dataset_version_id is None:
        raise ValueError("模型评估必须绑定冻结数据集")
    dataset = db.get(DatasetVersion, evaluation.dataset_version_id)
    if dataset is None:
        raise LookupError("绑定的数据集不存在")
    if dataset.status != "frozen" or not dataset.snapshot_ndjson or not dataset.snapshot_sha256:
        raise ValueError("模型评估必须使用已冻结且有快照内容的数据集")
    if dataset.row_count <= 0:
        raise ValueError("模型评估不能使用空数据集")
    if evaluation.split.lower() != "test":
        raise ValueError("只有 test split 可以进入发布审批")
    # 客户端自报的指标只留作对照，但写了就必须是 0–1 的有限数值
    for key, value in (evaluation.metrics or {}).items():
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
            raise ValueError(f"指标 {key} 必须是有限数值")
        if not 0 <= float(value) <= 1:
            raise ValueError(f"指标 {key} 必须在 0 到 1 之间")
    if not evaluation.predictions:
        raise ValueError("模型评估必须提交测试组的逐条预测，由平台重算指标后才能审批")
    threshold = float((evaluation.platform_metrics or {}).get("threshold", 0.5))
    metrics = recompute_metrics(dataset, split="test", predictions=evaluation.predictions, threshold=threshold)
    if metrics["positives"] == 0 or metrics["negatives"] == 0:
        raise ValueError("测试组至少要有一个阳性和一个阴性样本，否则指标没有意义")
    evaluation.platform_metrics = metrics
    return dataset


def approve_model_evaluation(
    db: Session,
    evaluation: ModelEvaluation,
    *,
    approved_by: str,
    now: datetime | None = None,
) -> ModelEvaluation:
    """通过评估审批闸门并落库。"""
    if evaluation.status == "approved":
        raise ValueError("模型评估已经审批通过")
    validate_evaluation_gate(db, evaluation)
    if not approved_by.strip():
        raise ValueError("approved_by 不能为空")
    evaluation.status = "approved"
    evaluation.approved_by = approved_by.strip()
    evaluation.approved_at = now or datetime.now(timezone.utc)
    db.flush()
    return evaluation
