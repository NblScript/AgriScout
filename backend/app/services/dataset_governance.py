"""数据集冻结与模型评估门禁。

该模块把人工标注、采样点和当时的分析结论组成可复现的 NDJSON 快照。
冻结之后快照字段只读；照片依然通过 ``photo_url`` 引用内容寻址存储。
"""
from __future__ import annotations

import hashlib
import json
import math
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Analysis, Annotation, CapturePoint, DatasetVersion, ModelEvaluation


SUPPORTED_METRICS = frozenset({"precision", "recall", "f1", "pr_auc", "map", "mAP"})


@dataclass(frozen=True)
class DatasetSnapshot:
    """构建但尚未写入数据库的确定性快照。"""

    ndjson: str
    sha256: str
    row_count: int
    summary: dict[str, Any]


def _iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _source_filter_clause(stmt, source_filter: dict[str, Any] | None):
    source_filter = source_filter or {}
    patrol_id = source_filter.get("patrol_id")
    if patrol_id is not None:
        stmt = stmt.where(Annotation.patrol_id == int(patrol_id))
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


def build_dataset_snapshot(
    db: Session,
    dataset: DatasetVersion,
    *,
    source_filter: dict[str, Any] | None = None,
) -> DatasetSnapshot:
    """从当前数据库构建排序稳定的 NDJSON 快照。

    每行对应一条人工标注，并带上照片 URL、空间/时间采样信息和机器分析结果。
    ``source_filter`` 缺省使用数据集上保存的过滤条件。
    """
    filter_value = dataset.source_filter if source_filter is None else source_filter
    stmt = (
        select(Annotation, CapturePoint, Analysis)
        .join(CapturePoint, Annotation.capture_point_id == CapturePoint.id)
        .outerjoin(Analysis, Analysis.capture_point_id == CapturePoint.id)
        .order_by(Annotation.patrol_id, CapturePoint.seq, Annotation.id)
    )
    stmt = _source_filter_clause(stmt, filter_value)

    rows: list[dict[str, Any]] = []
    for ann, point, analysis in db.execute(stmt):
        rows.append(
            {
                "schema_version": "agriscout.dataset.v1",
                "annotation_id": ann.id,
                "patrol_id": ann.patrol_id,
                "capture_point_id": point.id,
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

    lines = [json.dumps(row, ensure_ascii=False, sort_keys=True, separators=(",", ":")) for row in rows]
    ndjson = "\n".join(lines) + ("\n" if lines else "")
    counts = Counter(row["label"] for row in rows)
    with_analysis = sum(row["analysis"] is not None for row in rows)
    summary = {
        "schema_version": "agriscout.dataset.v1",
        "row_count": len(rows),
        "labels": dict(sorted(counts.items())),
        "with_analysis": with_analysis,
        "without_analysis": len(rows) - with_analysis,
        "source_filter": filter_value or {},
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
    now: datetime | None = None,
) -> DatasetSnapshot:
    """构建并冻结数据集；无标注样本或重复修改会失败。"""
    if dataset.status == "frozen":
        raise ValueError("数据集已冻结，不能重新生成快照")
    if dataset.status not in {"draft", "candidate"}:
        raise ValueError(f"数据集状态不允许冻结: {dataset.status}")
    snapshot = build_dataset_snapshot(db, dataset)
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


def validate_evaluation_gate(db: Session, evaluation: ModelEvaluation) -> DatasetVersion:
    """验证模型发布前置条件，失败抛出 ValueError/LookupError。"""
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
    if not isinstance(evaluation.metrics, dict) or not evaluation.metrics:
        raise ValueError("模型评估必须提供指标")
    supported = [key for key in evaluation.metrics if key in SUPPORTED_METRICS]
    if not supported:
        raise ValueError("至少提供 precision、recall、f1、pr_auc 或 mAP 指标")
    for key, value in evaluation.metrics.items():
        if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(float(value)):
            raise ValueError(f"指标 {key} 必须是有限数值")
        if not 0 <= float(value) <= 1:
            raise ValueError(f"指标 {key} 必须在 0 到 1 之间")
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
