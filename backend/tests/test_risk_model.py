"""risk-lr 风险模型：训练导出、文件校验、线上预测，以及训练—上线特征一致性（执行计划 0009）。"""
import json
import math

import pytest

from app.core.config import get_settings
from app.services.offline_replay import build_samples
from app.services.risk_features import IMAGE_FEATURES
from app.services.risk_model import load_model, model_path, parse_model, save_model_file
from app.tools.train_risk_lr import train_risk_model
from conftest import png_b64
from test_offline_replay import _ring_world

BASE = "/api/v1"
TARGET = "首次显症"
GREEN, BROWN = png_b64((40, 160, 60)), png_b64((120, 85, 50))


def _doc(version="risk-lr-test", horizon_hours=72):
    world = build_samples(_ring_world())
    return train_risk_model({1: world, 2: world}, version=version, target_event=TARGET, horizon_hours=horizon_hours)


@pytest.fixture()
def model_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(get_settings(), "risk_model_dir", str(tmp_path))
    return tmp_path


def test_train_export_load_roundtrip(model_dir):
    doc = _doc()
    assert doc["model"]["features"] == list(IMAGE_FEATURES)
    assert 0 < doc["prevalence"] < 1 and doc["cv"]["pr_auc"] is not None
    assert [row["test_field_id"] for row in doc["leave_one_field_out"]] == [1, 2]
    sha = save_model_file(doc, model_path("risk-lr-test"))
    loaded = load_model("risk-lr-test")
    assert loaded.sha256 == sha and loaded.horizon_hours == 72 and loaded.history_days == 30
    features = {"img_now": 0.1, "img_hist_max": 0.1, "img_delta": 0.0, "nbr_now": 0.4, "nbr_delta": 0.2}
    assert 0 < loaded.model.predict(features) < 1


def test_tampered_or_renamed_model_file_is_rejected(model_dir):
    save_model_file(_doc(), model_path("risk-lr-test"))
    doc = json.loads(model_path("risk-lr-test").read_text(encoding="utf-8"))
    doc["model"]["weights"][1] += 1.0  # 手改系数
    with pytest.raises(ValueError, match="SHA-256"):
        parse_model(doc, "risk-lr-test")
    with pytest.raises(ValueError, match="版本号"):
        parse_model(json.loads(model_path("risk-lr-test").read_text(encoding="utf-8")), "risk-lr-other")


@pytest.mark.parametrize("version", ["risk-lr-../../etc/passwd", "risk-lr-a/b", "risk-lr-", "risk-lr-a\\b", "risk-lr-a..b"])
def test_model_version_cannot_escape_model_dir(version):
    with pytest.raises(ValueError, match="不合法"):
        model_path(version)


def test_training_needs_both_classes():
    world = [s for s in build_samples(_ring_world()) if s.label != 1]
    with pytest.raises(ValueError, match="阳性和阴性"):
        train_risk_model({1: world}, version="risk-lr-x", target_event=TARGET, horizon_hours=72)


# ---------------------------------------------------------------- 线上预测


def _grid_point(ix: int, iy: int) -> tuple[float, float]:
    """地块原点 (10, 10) 起、2.5 m 网格中心的经纬度。"""
    lng = 10 + (ix * 2.5 + 1.25) / (111_320 * math.cos(math.radians(10)))
    lat = 10 + (iy * 2.5 + 1.25) / 111_320
    return round(lng, 9), round(lat, 9)


def _mini_season(client):
    """3×3 个区域、3 趟巡检：中心与角落先发病、再蔓延到一个邻居；第 3 趟角落缺照片。"""
    field_id = client.post(f"{BASE}/fields", json={
        "name": "模型测试田",
        "boundary": {"type": "Polygon", "coordinates": [[[10, 10], [10.001, 10], [10.001, 10.001], [10, 10.001], [10, 10]]]},
    }).json()["id"]
    client.post(f"{BASE}/devices", json={"code": "lr-01", "name": "模型车", "type": "rover"})
    photos = {
        0: {},
        3: {(1, 1): BROWN, (0, 0): BROWN},
        # 角落上一趟有病斑、这趟缺照片：它作为邻居的「上一趟」分数必须照样参与计算
        6: {(1, 1): BROWN, (1, 2): BROWN, (0, 0): None},
    }
    patrols = []
    for day, overrides in photos.items():
        date = f"2026-09-{1 + day:02d}"
        points = []
        for seq, (ix, iy) in enumerate((ix, iy) for ix in range(3) for iy in range(3)):
            lng, lat = _grid_point(ix, iy)
            points.append({"seq": seq, "lng": lng, "lat": lat, "captured_at": f"{date}T08:{seq:02d}:00+00:00",
                           "photo": overrides.get((ix, iy), GREEN)})
        pid = client.post(f"{BASE}/ingest/patrol", json={
            "patrol": {"field_id": field_id, "device": "lr-01", "started_at": f"{date}T08:00:00+00:00"},
            "capture_points": points,
        }).json()["patrol_id"]
        patrols.append({"day": day, "patrol_id": pid})
    return field_id, patrols


def _generate(client, patrol_id, **overrides):
    body = {"target_event": TARGET, "forecast_hours": 72, "model_version": "risk-lr-test", **overrides}
    return client.post(f"{BASE}/patrols/{patrol_id}/risk-predictions/generate", json=body)


def test_online_features_equal_offline_training_features(client, model_dir):
    """训练—上线一致性：同一份数据，离线重放（训练用）与线上预测算出的特征逐项相等。"""
    from app.core.db import get_session_factory
    from app.main import app
    from app.tools.replay_eval import TRUTH_SCHEMA, load_input

    save_model_file(_doc(), model_path("risk-lr-test"))
    field_id, patrols = _mini_season(client)
    last = patrols[-1]
    resp = _generate(client, last["patrol_id"])
    assert resp.status_code == 200, resp.text
    online = {p["observation_key"]: p["evidence"]["feature_values"] for p in resp.json()}

    truth = {"schema": TRUTH_SCHEMA, "field_id": field_id, "target_event": TARGET, "model_version": "risk-lr-test",
             "horizon_hours": 72, "event_severity": 0.1, "patrols": patrols,
             "weather": [{"favourability": 0.5, "rain_mm": 0.0, "humidity_pct": 70.0}] * 12, "severity": {}}
    db = app.dependency_overrides[get_session_factory]()()
    try:
        offline = {s.region: s.features for s in build_samples(load_input(db, truth)) if s.day == last["day"]}
    finally:
        db.close()

    assert len(online) == 8  # 角落这趟缺照片：没有它的预测，但它仍作为邻居参与计算
    for key, values in online.items():
        assert values == {name: round(offline[key][name], 6) for name in IMAGE_FEATURES}, key
    center = online[f"field-{field_id}/grid2.5m/1_1"]
    assert center["img_now"] > 0 and center["nbr_now"] > 0  # 中心本身和邻居 (1,2) 都有病斑


def test_lr_predictions_carry_model_provenance_and_relative_levels(client, model_dir):
    save_model_file(_doc(), model_path("risk-lr-test"))
    _, patrols = _mini_season(client)
    preds = _generate(client, patrols[-1]["patrol_id"]).json()
    first = preds[0]
    model = first["evidence"]["model"]
    assert first["model_version"] == "risk-lr-test"
    assert model["approval"] == {"status": "unapproved"} and len(model["sha256"]) == 64
    assert set(first["evidence"]["contributions"]) == set(IMAGE_FEATURES)
    assert all(p["confidence"] == pytest.approx(abs(2 * p["probability"] - 1), abs=1e-6) for p in preds)
    assert {p["level"] for p in preds} <= {"low", "medium", "high"}


def test_lr_request_must_match_training_target(client, model_dir):
    save_model_file(_doc(), model_path("risk-lr-test"))
    _, patrols = _mini_season(client)
    pid = patrols[-1]["patrol_id"]
    assert _generate(client, pid, forecast_hours=48).status_code == 422
    assert _generate(client, pid, target_event="别的病").status_code == 422
    assert _generate(client, pid, region_cell_m=5.0).status_code == 422
    missing = _generate(client, pid, model_version="risk-lr-missing")
    assert missing.status_code == 422 and "不存在" in missing.json()["detail"]
    bad = _generate(client, pid, model_version="risk-lr-../../secret")
    assert bad.status_code == 422 and "不合法" in bad.json()["detail"]
    # 默认仍是启发式，不受模型文件影响
    heuristic = client.post(f"{BASE}/patrols/{pid}/risk-predictions/generate", json={"target_event": TARGET})
    assert heuristic.status_code == 200 and heuristic.json()[0]["model_version"] == "risk-heuristic-v2"


def test_lr_revisit_tasks_use_evidence_quality_not_model_certainty(client, model_dir):
    """risk-lr 的置信度是 |2p−1|，不是证据质量；高风险区域必须生成复巡而不是随机抽查（D13）。"""
    save_model_file(_doc(), model_path("risk-lr-test"))
    field_id, patrols = _mini_season(client)
    preds = {p["id"]: p for p in _generate(client, patrols[-1]["patrol_id"]).json()}
    for pred in preds.values():
        quality = pred["evidence"]["evidence_quality"]
        assert 0 <= quality["score"] <= 1 and quality["observations"] >= 1
        assert pred["evidence"]["model"]["level_thresholds"]["high"] > 0

    tasks = client.post(f"{BASE}/revisit-tasks/generate",
                        json={"field_id": field_id, "patrol_id": patrols[-1]["patrol_id"], "limit": 8}).json()
    assert tasks
    for task in tasks:
        pred = preds[task["risk_prediction_id"]]
        signals = task["rationale"]["signals"]
        assert signals["quality"] == pytest.approx(pred["evidence"]["evidence_quality"]["score"])
        assert signals["uncertainty"] == pytest.approx(1 - pred["confidence"])
        if pred["level"] == "high":
            assert task["task_type"] != "random", (pred["observation_key"], signals)
    assert any(task["task_type"] == "revisit" for task in tasks)
