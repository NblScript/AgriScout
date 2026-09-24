from datetime import datetime, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import Base
from app.models import Analysis, Annotation, CapturePoint, DatasetVersion, Field, ModelEvaluation, Patrol
from app.services.dataset_governance import (
    approve_model_evaluation,
    build_dataset_snapshot,
    freeze_dataset_version,
    validate_evaluation_gate,
)


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _seed(db: Session) -> DatasetVersion:
    field = Field(name="G-1", boundary={"type": "Polygon", "coordinates": []})
    db.add(field)
    db.flush()
    patrol = Patrol(field_id=field.id, started_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    db.add(patrol)
    db.flush()
    point = CapturePoint(
        patrol_id=patrol.id, seq=1, distance_m=0.5, lng=120.1, lat=30.2,
        captured_at=datetime(2026, 1, 1, tzinfo=timezone.utc), photo_url="/media/hash.jpg",
    )
    db.add(point)
    db.flush()
    db.add(Analysis(
        capture_point_id=point.id, patrol_id=patrol.id, analyzer_version="placeholder-v0",
        growth_stage={"name": "拔节"}, vigor_level=4, ndvi=0.71,
        disease_detections=[], risk_score=0.1, detail={"green_ratio": 0.7},
    ))
    db.add(Annotation(
        capture_point_id=point.id, patrol_id=patrol.id, label="normal",
        annotator_name="tester", note="ok",
    ))
    dataset = DatasetVersion(
        name="wheat", version="2026.01", source_filter={"patrol_id": patrol.id},
        label_schema={"labels": ["normal", "suspected_disease"]}, created_by="tester",
    )
    db.add(dataset)
    db.commit()
    db.refresh(dataset)
    return dataset


def test_freeze_persists_deterministic_snapshot_and_photo_url(db):
    dataset = _seed(db)
    snapshot = build_dataset_snapshot(db, dataset)
    assert snapshot.row_count == 1
    assert '"photo_url":"/media/hash.jpg"' in snapshot.ndjson
    assert snapshot.sha256

    freeze_dataset_version(db, dataset, now=datetime(2026, 1, 2, tzinfo=timezone.utc))
    db.commit()
    assert dataset.status == "frozen"
    assert dataset.row_count == 1
    assert dataset.snapshot_sha256 == snapshot.sha256
    assert dataset.snapshot_ndjson == snapshot.ndjson
    with pytest.raises(ValueError, match="已冻结"):
        freeze_dataset_version(db, dataset)


def test_empty_dataset_cannot_freeze(db):
    dataset = DatasetVersion(name="empty", version="1", source_filter={}, label_schema={})
    db.add(dataset)
    db.commit()
    with pytest.raises(ValueError, match="空数据集"):
        freeze_dataset_version(db, dataset)


def test_model_approval_requires_frozen_nonempty_test_dataset_and_bounded_metrics(db):
    dataset = _seed(db)
    evaluation = ModelEvaluation(
        dataset_version_id=dataset.id, model_name="yolo", model_version="v1", split="test",
        metrics={"f1": 0.83}, evaluated_at=datetime.now(timezone.utc),
    )
    db.add(evaluation)
    db.commit()
    with pytest.raises(ValueError, match="冻结"):
        validate_evaluation_gate(db, evaluation)

    freeze_dataset_version(db, dataset)
    approve_model_evaluation(db, evaluation, approved_by="reviewer")
    assert evaluation.status == "approved"
    assert evaluation.approved_by == "reviewer"


@pytest.mark.parametrize(
    "split,metrics,match",
    [
        ("validation", {"f1": 0.8}, "test split"),
        ("test", {"accuracy": 0.8}, "至少提供"),
        ("test", {"f1": 1.2}, "0 到 1"),
        ("test", {"f1": float("nan")}, "有限数值"),
    ],
)
def test_model_gate_rejects_invalid_metrics(db, split, metrics, match):
    dataset = _seed(db)
    freeze_dataset_version(db, dataset)
    evaluation = ModelEvaluation(
        dataset_version_id=dataset.id, model_name="yolo", model_version="v1", split=split,
        metrics=metrics, evaluated_at=datetime.now(timezone.utc),
    )
    with pytest.raises(ValueError, match=match):
        validate_evaluation_gate(db, evaluation)


def test_model_gate_rejects_unbound_evaluation(db):
    evaluation = ModelEvaluation(
        model_name="yolo", model_version="v1", split="test", metrics={"f1": 0.8},
        evaluated_at=datetime.now(timezone.utc),
    )
    with pytest.raises(ValueError, match="绑定"):
        validate_evaluation_gate(db, evaluation)
