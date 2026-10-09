"""计划 0007 P1-7（决策 D24）：数据集按「地块 + 田间日期」整组划分，模型评估由平台对照快照测试组重算指标。"""
import json
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.core.db import Base
from app.models import Annotation, CapturePoint, DatasetVersion, Field, ModelEvaluation, Patrol
from app.services.dataset_governance import (
    SplitSpec,
    assign_splits,
    build_dataset_snapshot,
    freeze_dataset_version,
    recompute_metrics,
    validate_evaluation_gate,
)

BASE = "/api/v1"
CN = timezone(timedelta(hours=8))


@pytest.fixture()
def db():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        yield session


def _field(db: Session, name: str) -> Field:
    field = Field(name=name, boundary={"type": "Polygon", "coordinates": []})
    db.add(field)
    db.flush()
    return field


def _day(db: Session, field: Field, day: int, labels: list[str]) -> None:
    """某地块 10 月 day 日早上的一趟巡检，每个标签一个点。"""
    start = datetime(2026, 10, day, 6, 0, tzinfo=CN)
    patrol = Patrol(field_id=field.id, started_at=start)
    db.add(patrol)
    db.flush()
    for seq, label in enumerate(labels):
        point = CapturePoint(
            patrol_id=patrol.id, seq=seq, lng=0.0, lat=0.0, captured_at=start + timedelta(minutes=seq),
            photo_url=f"/media/{field.id}-{day}-{seq}.jpg", observation_key=f"R1-P{seq + 1:03d}",
        )
        db.add(point)
        db.flush()
        db.add(Annotation(capture_point_id=point.id, patrol_id=patrol.id, label=label, annotator_name="农技员"))
    db.flush()


def _dataset(db: Session, **source_filter) -> DatasetVersion:
    dataset = DatasetVersion(name="gh", version=f"v{db.query(DatasetVersion).count() + 1}",
                             source_filter=source_filter, label_schema={"target": "disease"})
    db.add(dataset)
    db.flush()
    return dataset


def _rows(dataset: DatasetVersion) -> list[dict]:
    return [json.loads(line) for line in dataset.snapshot_ndjson.splitlines()]


def _season(db: Session) -> tuple[Field, Field]:
    """两个棚各 6 天，每天一阴一阳。"""
    a, b = _field(db, "1 号棚"), _field(db, "2 号棚")
    for field in (a, b):
        for day in range(1, 7):
            _day(db, field, day, ["normal", "downy_mildew_early"])
    return a, b


def test_assign_splits_is_deterministic_keeps_groups_whole_and_always_has_test():
    sizes = {f"1:2026-10-{d:02d}": 10 + d for d in range(1, 21)}
    spec = SplitSpec(seed=7)
    first, again = assign_splits(sizes, spec), assign_splits(dict(reversed(sizes.items())), spec)
    assert first == again  # 与输入顺序无关
    assert set(first.values()) == {"train", "val", "test"}
    total = sum(sizes.values())
    test_rows = sum(sizes[k] for k, v in first.items() if v == "test")
    # 测试组填到刚超过 15%：差距不超过一组
    assert 0.15 * total <= test_rows < 0.15 * total + max(sizes.values())
    assert assign_splits(sizes, SplitSpec(seed=8)) != first  # 换种子换划分
    # 只有两组时也先保证测试组，再给验证组
    assert sorted(assign_splits({"x": 5, "y": 5}, spec).values()) == ["test", "val"]


@pytest.mark.parametrize("kwargs,match", [
    ({"group_by": "plant"}, "group_by"),
    ({"ratios": {"train": 0.8, "test": 0.2}}, "三份"),
    ({"ratios": {"train": 0.8, "val": 0.1, "test": 0.2}}, "之和"),
    ({"ratios": {"train": 0.9, "val": 0.1, "test": 0.0}}, "测试组"),
])
def test_split_spec_rejects_bad_parameters(kwargs, match):
    with pytest.raises(ValueError, match=match):
        SplitSpec(**kwargs)


def test_snapshot_rows_carry_group_and_same_day_stays_in_one_split(db):
    _season(db)
    dataset = _dataset(db)
    freeze_dataset_version(db, dataset, split=SplitSpec(seed=3))
    rows = _rows(dataset)
    assert len(rows) == 24 and rows[0]["schema_version"] == "agriscout.dataset.v2"
    by_group: dict[str, set[str]] = {}
    for row in rows:
        assert row["group"] == f"{row['field_id']}:{row['field_date']}"
        by_group.setdefault(row["group"], set()).add(row["split"])
    assert all(len(splits) == 1 for splits in by_group.values())
    split = dataset.snapshot_summary["split"]
    assert split["seed"] == 3 and split["method"] == "group-shuffle-v1"
    assert sum(split["counts"].values()) == 24 and split["counts"]["test"] >= 4
    assert sorted(g for groups in split["groups"].values() for g in groups) == sorted(by_group)
    assert dataset.snapshot_summary["evaluation"]["positive_labels"] == [
        "downy_mildew_early", "downy_mildew_symptomatic", "suspected_disease",
    ]


def test_same_seed_reproduces_snapshot_and_field_grouping_holds_out_a_whole_greenhouse(db):
    a, _ = _season(db)
    one, two = _dataset(db), _dataset(db)
    assert build_dataset_snapshot(db, one, split=SplitSpec(seed=5)).sha256 == \
        build_dataset_snapshot(db, two, split=SplitSpec(seed=5)).sha256
    by_field = build_dataset_snapshot(db, one, split=SplitSpec(group_by="field"))
    rows = [json.loads(line) for line in by_field.ndjson.splitlines()]
    assert {row["group"] for row in rows} == {str(a.id), str(a.id + 1)}
    # 两个棚：一个整棚进测试组，另一个整棚进验证组
    assert {row["field_id"]: row["split"] for row in rows} in (
        {a.id: "test", a.id + 1: "val"}, {a.id: "val", a.id + 1: "test"},
    )


def test_source_filter_by_field_and_field_date_range(db):
    a, _ = _season(db)
    dataset = _dataset(db, field_id=a.id, date_from="2026-10-02", date_to="2026-10-04")
    snapshot = build_dataset_snapshot(db, dataset)
    rows = [json.loads(line) for line in snapshot.ndjson.splitlines()]
    assert {row["field_id"] for row in rows} == {a.id}
    assert sorted({row["field_date"] for row in rows}) == ["2026-10-02", "2026-10-03", "2026-10-04"]
    with pytest.raises(ValueError, match="YYYY-MM-DD"):
        build_dataset_snapshot(db, _dataset(db, date_from="10/02"))


def _frozen_season(db: Session) -> DatasetVersion:
    _season(db)
    dataset = _dataset(db)
    freeze_dataset_version(db, dataset, split=SplitSpec(seed=1))
    return dataset


def _test_rows(dataset: DatasetVersion) -> list[dict]:
    return [row for row in _rows(dataset) if row["split"] == "test"]


def test_recompute_metrics_counts_threshold_and_average_precision(db):
    dataset = _frozen_season(db)
    rows = _test_rows(dataset)
    positives = [r for r in rows if r["label"] != "normal"]
    negatives = [r for r in rows if r["label"] == "normal"]
    # 一个阳性漏判（0.4 < 0.5），一个阴性误报（0.6）
    predictions = [{"annotation_id": r["annotation_id"], "score": 0.9} for r in positives[1:]]
    predictions.append({"annotation_id": positives[0]["annotation_id"], "score": 0.4})
    predictions += [{"annotation_id": r["annotation_id"], "score": 0.1} for r in negatives[1:]]
    predictions.append({"annotation_id": negatives[0]["annotation_id"], "score": 0.6})
    m = recompute_metrics(dataset, split="test", predictions=predictions, threshold=0.5)
    p, n = len(positives), len(negatives)
    assert (m["n"], m["positives"], m["negatives"]) == (p + n, p, n)
    assert (m["tp"], m["fp"], m["fn"], m["tn"]) == (p - 1, 1, 1, n - 1)
    assert m["precision"] == round((p - 1) / p, 6) and m["recall"] == round((p - 1) / p, 6)
    assert m["f1"] == m["precision"]
    assert 0 < m["pr_auc"] < 1


def test_recompute_metrics_rejects_missing_extra_duplicate_and_ignores_other_label(db):
    dataset = _frozen_season(db)
    rows = _test_rows(dataset)
    full = [{"annotation_id": r["annotation_id"], "score": 0.5} for r in rows]
    with pytest.raises(ValueError, match="缺少"):
        recompute_metrics(dataset, split="test", predictions=full[1:], threshold=0.5)
    train_id = next(r["annotation_id"] for r in _rows(dataset) if r["split"] == "train")
    with pytest.raises(ValueError, match="不属于"):
        recompute_metrics(dataset, split="test", predictions=[*full, {"annotation_id": train_id, "score": 0.1}],
                          threshold=0.5)
    with pytest.raises(ValueError, match="重复"):
        recompute_metrics(dataset, split="test", predictions=[*full, full[0]], threshold=0.5)


def test_other_label_is_not_scored(db):
    field = _field(db, "1 号棚")
    _day(db, field, 1, ["normal", "downy_mildew_early", "other"])
    dataset = _dataset(db)
    freeze_dataset_version(db, dataset)
    rows = _rows(dataset)
    scored = [{"annotation_id": r["annotation_id"], "score": 0.5} for r in rows if r["label"] != "other"]
    assert recompute_metrics(dataset, split="test", predictions=scored, threshold=0.5)["n"] == 2


def test_gate_rejects_snapshot_frozen_before_splits_and_test_without_both_classes(db):
    dataset = _frozen_season(db)
    legacy = DatasetVersion(name="old", version="v1", status="frozen", row_count=1,
                            snapshot_ndjson=dataset.snapshot_ndjson, snapshot_sha256="x",
                            snapshot_summary={"schema_version": "agriscout.dataset.v1", "row_count": 1})
    db.add(legacy)
    db.flush()
    evaluation = ModelEvaluation(dataset_version_id=legacy.id, model_name="m", model_version="1", split="test",
                                 evaluated_at=datetime.now(timezone.utc),
                                 predictions=[{"annotation_id": 1, "score": 0.5}])
    with pytest.raises(ValueError, match="重新冻结"):
        validate_evaluation_gate(db, evaluation)

    field = _field(db, "3 号棚")
    _day(db, field, 9, ["normal", "normal"])
    only_negative = _dataset(db, field_id=field.id)
    freeze_dataset_version(db, only_negative)
    evaluation = ModelEvaluation(
        dataset_version_id=only_negative.id, model_name="m", model_version="1", split="test",
        evaluated_at=datetime.now(timezone.utc),
        predictions=[{"annotation_id": r["annotation_id"], "score": 0.2} for r in _rows(only_negative)],
    )
    with pytest.raises(ValueError, match="一个阳性和一个阴性"):
        validate_evaluation_gate(db, evaluation)


def _api_setup(client) -> tuple[int, list[dict]]:
    field_id = client.post(f"{BASE}/fields", json={
        "name": "划分测试棚", "boundary": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 0]]]},
    }).json()["id"]
    client.post(f"{BASE}/devices", json={"code": "split-01", "name": "划分小车", "type": "rover"})
    annotations = []
    for day in (1, 2, 3):
        at = f"2026-10-0{day}T06:00:00+08:00"
        patrol_id = client.post(f"{BASE}/ingest/patrol", json={
            "patrol": {"field_id": field_id, "device": "split-01", "started_at": at},
            "capture_points": [
                {"seq": seq, "lng": 0.5, "lat": 0.5, "captured_at": at, "photo": "https://example.com/p.jpg"}
                for seq in (0, 1)
            ],
        }).json()["patrol_id"]
        points = client.get(f"{BASE}/capture-points?patrol_id={patrol_id}&limit=10").json()["items"]
        for point, label in zip(points, ("normal", "downy_mildew_early")):
            annotations.append(client.post(f"{BASE}/capture-points/{point['id']}/annotations",
                                           json={"label": label, "annotator_name": "农技员"}).json())
    return field_id, annotations


def test_api_freeze_with_split_and_evaluation_recomputed_on_create(client):
    field_id, _ = _api_setup(client)
    dataset = client.post(f"{BASE}/datasets/versions", json={
        "name": "gh", "version": "v1", "source_filter": {"field_id": field_id}, "label_schema": {"target": "disease"},
    }).json()
    bad = client.post(f"{BASE}/datasets/versions/{dataset['id']}/freeze",
                      json={"split": {"ratios": {"train": 1.0, "val": 0.0, "test": 0.0}}})
    assert bad.status_code == 422 and "测试组" in bad.json()["detail"]
    frozen = client.post(f"{BASE}/datasets/versions/{dataset['id']}/freeze", json={"split": {"seed": 11}}).json()
    split = frozen["snapshot_summary"]["split"]
    assert split["seed"] == 11 and split["counts"] == {"train": 2, "val": 2, "test": 2}

    snapshot = client.get(f"{BASE}/datasets/versions/{dataset['id']}/snapshot").text
    test_rows = [row for row in map(json.loads, snapshot.splitlines()) if row["split"] == "test"]
    body = {"dataset_version_id": dataset["id"], "model_name": "dm-cls", "model_version": "v0", "split": "test",
            "evaluated_at": "2026-10-09T10:00:00+00:00", "threshold": 0.5}
    missing = client.post(f"{BASE}/model-evaluations", json={
        **body, "predictions": [{"annotation_id": test_rows[0]["annotation_id"], "score": 0.9}],
    })
    assert missing.status_code == 422 and "缺少" in missing.json()["detail"]
    scores = {"normal": 0.2, "downy_mildew_early": 0.7}
    created = client.post(f"{BASE}/model-evaluations", json={
        **body, "metrics": {"f1": 0.99},
        "predictions": [{"annotation_id": r["annotation_id"], "score": scores[r["label"]]} for r in test_rows],
    })
    assert created.status_code == 201
    evaluation = created.json()
    assert "predictions" not in evaluation and evaluation["metrics"] == {"f1": 0.99}
    assert evaluation["platform_metrics"]["f1"] == 1.0 and evaluation["platform_metrics"]["n"] == 2
    approved = client.post(f"{BASE}/model-evaluations/{evaluation['id']}/approve", json={"approved_by": "负责人"})
    assert approved.status_code == 200 and approved.json()["status"] == "approved"

    no_predictions = client.post(f"{BASE}/model-evaluations", json=body).json()
    rejected = client.post(f"{BASE}/model-evaluations/{no_predictions['id']}/approve", json={"approved_by": "负责人"})
    assert rejected.status_code == 422 and "逐条预测" in rejected.json()["detail"]
