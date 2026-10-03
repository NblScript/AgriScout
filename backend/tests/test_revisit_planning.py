"""计划 0015：旧复巡接口下沉——按区域去重、全量排序，与离线重放的联合策略同一实现。"""
from datetime import datetime, timedelta, timezone

import pytest

from app.services.active_learning import revisit_candidate, select_revisits
from conftest import png_b64
from test_observation_units import _package, _point, _setup

BASE = "/api/v1"
TARGET = "霜霉病显症"
COLORS = [png_b64((40 + 6 * i, 160 - 8 * i, 60)) for i in range(13)]  # 13 种颜色 → 区域风险各不相同


def _ingest_13_units(client, field_id, day="2026-10-01"):
    """60 个点落在 13 株上（技术债台账的复现场景：60 点 13 区域取 5 条）。"""
    points = [_point(seq, f"R01-P{seq % 13 + 1:03d}", day=day, side="under", photo=COLORS[seq % 13])
              for seq in range(60)]
    patrol_id = client.post(f"{BASE}/ingest/patrol", json=_package(field_id, points, day=day)).json()["patrol_id"]
    preds = client.post(f"{BASE}/patrols/{patrol_id}/risk-predictions/generate",
                        json={"target_event": TARGET, "forecast_hours": 72}).json()
    return patrol_id, preds


def _generate(client, field_id, **extra):
    resp = client.post(f"{BASE}/revisit-tasks/generate", json={"field_id": field_id, "limit": 5, **extra})
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_tech_debt_scenario_selects_five_distinct_regions(client):
    field_id = _setup(client)
    _, preds = _ingest_13_units(client, field_id)
    assert len(preds) == 60 and len({p["observation_key"] for p in preds}) == 13
    tasks = _generate(client, field_id)
    assert len(tasks) == 5
    assert len({t["rationale"]["region"] for t in tasks}) == 5
    assert all(t["task_type"] == "revisit" and t["observation_unit_id"] for t in tasks)
    assert all(t["rationale"]["candidates"] == 13 for t in tasks)
    # 重复调用不新建任务
    again = _generate(client, field_id)
    assert [t["id"] for t in again] == [t["id"] for t in tasks]


def test_online_selection_matches_shared_joint_strategy(client):
    """线上与离线重放用同一套候选构造和选择：按同样的输入重算，选中的区域和顺序完全一致。"""
    field_id = _setup(client)
    _, preds = _ingest_13_units(client, field_id)
    tasks = _generate(client, field_id)

    best: dict[str, dict] = {}
    for p in preds:
        cur = best.get(p["observation_key"])
        if cur is None or (p["probability"], p["id"]) > (cur["probability"], cur["id"]):
            best[p["observation_key"]] = p
    candidates = []
    for key in sorted(best):
        p = best[key]
        group = [q for q in preds if q["observation_key"] == key]
        flags = [q["evidence"]["features"]["image_quality"]["ok"] for q in group]
        region = p["evidence"]["region"]
        history = region["history_risk_scores"]
        delta = region["region_risk_score"] - history[-1] if history else 0.0
        candidates.append(revisit_candidate(
            key, probability=p["probability"], image_delta=delta, neighbor_delta=0.0,
            day=datetime.fromisoformat(p["forecast_start"]).timestamp() / 86400, last_visit_day=None,
            interval_days=1.0, quality=sum(flags) / len(flags),
        ))
    expected = [row.candidate_id for row in select_revisits(candidates, 5)]
    assert [t["rationale"]["region"] for t in tasks] == expected


def test_quality_falls_back_to_d13_without_image_quality(client):
    """老预测没有图像质量记录时，质量信号退回 D13 口径（启发式用置信度）。"""
    field_id = _setup(client)
    patrol_id, preds = _ingest_13_units(client, field_id)
    start = datetime(2026, 10, 1, 9, tzinfo=timezone.utc)
    created = client.post(f"{BASE}/risk-predictions", json={
        "patrol_id": patrol_id, "capture_point_id": preds[0]["capture_point_id"], "observation_key": "legacy-region",
        "target_event": "旧口径", "forecast_hours": 48, "forecast_start": start.isoformat(),
        "forecast_end": (start + timedelta(hours=48)).isoformat(), "probability": 0.95, "level": "high",
        "confidence": 0.2, "model_version": "risk-heuristic-v2", "evidence": {},
    })
    assert created.status_code == 201, created.text
    tasks = _generate(client, field_id, limit=13 + 1)
    legacy = next(t for t in tasks if t["rationale"]["region"] == "legacy-region")
    assert legacy["rationale"]["quality_source"] == "d13"
    assert legacy["rationale"]["signals"]["quality"] == pytest.approx(0.2)
    assert {t["rationale"]["quality_source"] for t in tasks if t is not legacy} == {"image_quality"}


def test_recent_completed_revisit_lowers_staleness(client):
    field_id = _setup(client)
    _ingest_13_units(client, field_id, day="2026-10-01")
    first = _generate(client, field_id, limit=13)
    done = first[0]
    for status in ("assigned", "running"):
        client.patch(f"{BASE}/revisit-tasks/{done['id']}", json={"status": status})
    finished = client.patch(f"{BASE}/revisit-tasks/{done['id']}",
                            json={"status": "completed", "completed_at": "2026-10-01T12:00:00+08:00"})
    assert finished.status_code == 200, finished.text

    patrol2, _ = _ingest_13_units(client, field_id, day="2026-10-02")
    second = _generate(client, field_id, patrol_id=patrol2, limit=13, patrol_interval_days=1.0)
    by_region = {t["rationale"]["region"]: t for t in second}
    revisited = by_region[done["rationale"]["region"]]
    assert revisited["rationale"]["last_revisit_days_ago"] == pytest.approx(0.75, abs=0.05)  # 前一天 12:00 → 次日约 06:00
    assert revisited["rationale"]["signals"]["representativeness"] == pytest.approx(0.25, abs=0.02)
    others = [t for key, t in by_region.items() if key != done["rationale"]["region"]]
    assert all(t["rationale"]["signals"]["representativeness"] == 1.0 for t in others)
