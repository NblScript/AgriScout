"""计划 0007 P1-9（决策 D25）：盲法复核——按种子抽样加固定参考、只给照片、两人独立判读、分歧二次判读、定论写标注。"""
import json
from datetime import date

import pytest

from app.core.security import hash_password
from app.models import Annotation, User
from app.services.blind_review import BatchSpec, Candidate, choose_items, cohen_kappa, eligible
from conftest import png_b64

BASE = "/api/v1"
PASSWORD = "blind-review-9"
BOUNDARY = {"type": "Polygon", "coordinates": [[[10, 10], [10.001, 10], [10.001, 10.001], [10, 10.001], [10, 10]]]}


def _spec(**kwargs) -> BatchSpec:
    base = {"field_id": 1, "date_from": date(2026, 10, 1), "date_to": date(2026, 10, 3), "sample_size": 5}
    return BatchSpec(**{**base, **kwargs})


def test_choose_items_keeps_every_reference_photo_samples_the_rest_and_shuffles_by_seed():
    candidates = [Candidate(i, f"R1-P{i % 10:03d}") for i in range(1, 41)]  # 每株 4 张
    chosen = choose_items(candidates, _spec(reference_keys=("R1-P003",), seed=1))
    reference = [pid for pid, origin in chosen if origin == "reference"]
    assert sorted(reference) == [3, 13, 23, 33]
    assert sum(origin == "random" for _, origin in chosen) == 5
    assert not {pid for pid, origin in chosen if origin == "random"} & set(reference)
    assert chosen == choose_items(list(reversed(candidates)), _spec(reference_keys=("R1-P003",), seed=1))
    assert chosen != choose_items(candidates, _spec(reference_keys=("R1-P003",), seed=2))
    # 随机部分不按 id 顺序排，参考株也不扎堆在前面
    assert [pid for pid, _ in chosen] != sorted(pid for pid, _ in chosen)


def test_eligible_drops_failed_attempts_and_needs_underside_view_when_asked():
    assert not eligible({"side": "under", "accepted": False}, "any")
    assert eligible({"side": "under", "accepted": True}, "under")
    assert not eligible({"side": "upper", "accepted": True}, "under")
    assert not eligible(None, "under") and eligible(None, "any")


@pytest.mark.parametrize("kwargs,match", [
    ({"date_from": date(2026, 10, 5)}, "起始日期"),
    ({"sample_size": 501}, "0 到 500"),
    ({"sample_size": 0}, "固定参考株"),
    ({"side": "left"}, "side"),
])
def test_batch_spec_validation(kwargs, match):
    with pytest.raises(ValueError, match=match):
        _spec(**kwargs)


def test_cohen_kappa():
    assert cohen_kappa([]) is None
    assert cohen_kappa([("a", "a"), ("b", "b")]) == 1.0
    # 一致率 0.75；期望一致率 (3×2 + 1×2) / 16 = 0.5 → κ = 0.5
    assert cohen_kappa([("a", "a"), ("a", "a"), ("b", "b"), ("a", "b")]) == 0.5
    assert cohen_kappa([("a", "a"), ("a", "a")]) == 1.0  # 只用到一个类别也算完全一致


# ---------------------------------------------------------------- 接口（真实登录，判读人取账号）


def _add_users(session_factory) -> None:
    with session_factory() as db:
        for username, role in (("op1", "operator"), ("op2", "operator"), ("op3", "operator"), ("view", "viewer")):
            db.add(User(username=username, display_name=f"{username} 姓名", password_hash=hash_password(PASSWORD),
                        role=role, is_active=True))
        db.commit()


def _headers(client, username: str) -> dict[str, str]:
    resp = client.post(f"{BASE}/auth/login", json={"username": username, "password": PASSWORD})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _seed(client, h) -> int:
    """一个棚 3 天，每天 3 株：叶背合格、叶背不合格（不应入批）、正面各一张。"""
    field_id = client.post(f"{BASE}/fields", json={"name": "盲评棚", "boundary": BOUNDARY,
                                                   "facility_type": "solar_greenhouse"}, headers=h).json()["id"]
    client.post(f"{BASE}/devices", json={"code": "gh-01", "name": "大棚车", "type": "rover"}, headers=h)
    for day in (1, 2, 3):
        points = []
        for plant in (1, 2, 3):
            for side, ok in (("under", True), ("under", False), ("upper", True)):
                seq = len(points)
                points.append({
                    "seq": seq, "lng": 10.0005, "lat": 10.0005, "captured_at": f"2026-10-0{day}T06:{seq:02d}:00+08:00",
                    "photo": png_b64((40 + seq, 150, 60)), "observation_key": f"R01-P00{plant}",
                    "route_chainage_m": 0.4 * plant, "distance_source": "encoder", "position_source": "tag",
                    "view": {"side": side, "pitch_deg": 35 if side == "under" else 0, "attempt": 1 if ok else 2,
                             "accepted": ok, "quality": {"method": "iq-rule-v1", "ok": ok}},
                })
        resp = client.post(f"{BASE}/ingest/patrol", headers=h, json={
            "schema_version": "2.0", "patrol": {"field_id": field_id, "device": "gh-01",
                                                "started_at": f"2026-10-0{day}T06:00:00+08:00"},
            "capture_points": points,
        })
        assert resp.status_code == 201, resp.text
    return field_id


def _drain(client, batch_id: int, h, label_of) -> list[dict]:
    """把这位判读人能拿到的照片都判完，返回拿到的任务。"""
    tasks = []
    while (task := client.get(f"{BASE}/blind-reviews/{batch_id}/next", headers=h).json()) is not None:
        tasks.append(task)
        resp = client.post(f"{BASE}/blind-reviews/{batch_id}/items/{task['item_id']}/votes", headers=h,
                           json={"label": label_of(task)})
        assert resp.status_code == 201, resp.text
        assert resp.json() == {"item_id": task["item_id"], "recorded": True}  # 不回传状态和定论
    return tasks


def test_blind_review_double_reading_dispute_adjudication_and_dataset(auth_env):
    client, session_factory = auth_env
    _add_users(session_factory)
    op1, op2, op3, viewer = (_headers(client, u) for u in ("op1", "op2", "op3", "view"))
    field_id = _seed(client, op1)

    empty = client.post(f"{BASE}/blind-reviews", headers=op1, json={
        "field_id": field_id, "name": "空", "date_from": "2026-09-01", "date_to": "2026-09-02", "sample_size": 5})
    assert empty.status_code == 422 and "没有符合条件" in empty.json()["detail"]

    created = client.post(f"{BASE}/blind-reviews", headers=op1, json={
        "field_id": field_id, "name": "10 月第一批", "date_from": "2026-10-01", "date_to": "2026-10-03",
        "sample_size": 4, "seed": 3, "reference_keys": ["R01-P002"]})
    assert created.status_code == 201, created.text
    batch = created.json()
    # 合格叶背共 9 张：参考株 R01-P002 的 3 张全收，其余 6 张随机抽 4 张
    assert batch["item_count"] == 7 and batch["created_by"] == "op1 姓名"
    assert batch["params"]["reference_keys"] == ["R01-P002"] and batch["summary"]["resolved"] == 0
    batch_id = batch["id"]

    task = client.get(f"{BASE}/blind-reviews/{batch_id}/next", headers=viewer).json()
    # 判读只给照片：没有株号、来源、模型分数，也没有别人的判读
    assert set(task) == {"batch_id", "item_id", "position", "item_count", "round", "photo_url", "prior_labels"}
    assert task["round"] == 1 and task["prior_labels"] == [] and task["position"] == 1
    denied = client.post(f"{BASE}/blind-reviews/{batch_id}/items/{task['item_id']}/votes", headers=viewer,
                         json={"label": "normal"})
    assert denied.status_code == 403

    first = _drain(client, batch_id, op1, lambda t: "normal")
    assert [t["position"] for t in first] == list(range(1, 8))
    again = client.post(f"{BASE}/blind-reviews/{batch_id}/items/{first[0]['item_id']}/votes", headers=op1,
                        json={"label": "normal"})
    assert again.status_code == 409 and "判读过" in again.json()["detail"]
    disputed_item = first[0]["item_id"]
    _drain(client, batch_id, op2, lambda t: "downy_mildew_early" if t["item_id"] == disputed_item else "normal")

    summary = client.get(f"{BASE}/blind-reviews/{batch_id}", headers=op1).json()["summary"]
    assert summary["status_counts"]["agreed"] == 6 and summary["status_counts"]["disputed"] == 1
    assert summary["pairs"] == 7 and summary["agreement"] == round(6 / 7, 4)
    assert summary["my_votes"] == 7
    # 没全部定论前不公开逐张结论
    early = client.get(f"{BASE}/blind-reviews/{batch_id}/results", headers=op1)
    assert early.status_code == 409 and "定论前" in early.json()["detail"]

    # 两人都判过的分歧照片只能交给第三人二次判读，并给出前两次判读（不含判读人）
    assert client.get(f"{BASE}/blind-reviews/{batch_id}/next", headers=op1).json() is None
    adjudication = _drain(client, batch_id, op3, lambda t: "downy_mildew_early")
    assert len(adjudication) == 1 and adjudication[0]["round"] == 2
    assert adjudication[0]["item_id"] == disputed_item
    assert sorted(adjudication[0]["prior_labels"]) == ["downy_mildew_early", "normal"]

    done = client.get(f"{BASE}/blind-reviews/{batch_id}", headers=op3).json()
    assert done["status"] == "done" and done["summary"]["resolved"] == 7
    assert done["summary"]["status_counts"]["adjudicated"] == 1
    late = client.post(f"{BASE}/blind-reviews/{batch_id}/items/{disputed_item}/votes", headers=op3,
                       json={"label": "normal"})
    assert late.status_code == 409
    results = client.get(f"{BASE}/blind-reviews/{batch_id}/results", headers=op1).json()
    assert [r["position"] for r in results] == list(range(1, 8))
    assert sorted(r["final_label"] for r in results) == ["downy_mildew_early"] + ["normal"] * 6
    assert {r["origin"] for r in results} == {"random", "reference"}
    assert sum(r["observation_key"] == "R01-P002" for r in results) == 3
    with session_factory() as db:
        annotations = db.query(Annotation).order_by(Annotation.id).all()
        assert len(annotations) == 7
        adjudicated = next(a for a in annotations if a.label == "downy_mildew_early")
        assert adjudicated.annotator_name == "盲评：op1 姓名、op2 姓名、op3 姓名"

    # 数据集只收这批盲评的定论（D24 source_filter）
    dataset = client.post(f"{BASE}/datasets/versions", headers=op1, json={
        "name": "blind-test", "version": "v1", "source_filter": {"blind_batch_id": batch_id}}).json()
    frozen = client.post(f"{BASE}/datasets/versions/{dataset['id']}/freeze", headers=op1, json={}).json()
    assert frozen["row_count"] == 7
    rows = [json.loads(line) for line in
            client.get(f"{BASE}/datasets/versions/{dataset['id']}/snapshot", headers=op1).text.splitlines()]
    assert all(row["blind_batch_ids"] == [batch_id] for row in rows)


def test_single_reading_batch_resolves_on_first_vote_and_reuses_existing_annotation(auth_env):
    client, session_factory = auth_env
    _add_users(session_factory)
    op1 = _headers(client, "op1")
    field_id = _seed(client, op1)
    batch = client.post(f"{BASE}/blind-reviews", headers=op1, json={
        "field_id": field_id, "name": "单人", "date_from": "2026-10-01", "date_to": "2026-10-01",
        "sample_size": 10, "side": "any", "double_review": False}).json()
    # side=any：当天合格的叶背 3 张 + 正面 3 张，不合格的 3 张不收
    assert batch["item_count"] == 6
    task = client.get(f"{BASE}/blind-reviews/{batch['id']}/next", headers=op1).json()
    assert client.get(f"{BASE}/blind-reviews/{batch['id']}/results", headers=op1).status_code == 409
    with session_factory() as db:
        from app.models import BlindReviewItem
        item = db.get(BlindReviewItem, task["item_id"])
        point, patrol = item.capture_point_id, item.capture_point.patrol_id
        db.add(Annotation(capture_point_id=point, patrol_id=patrol, label="normal", annotator_name="开放复核人"))
        db.commit()
    _drain(client, batch["id"], op1, lambda t: "normal")
    done = client.get(f"{BASE}/blind-reviews/{batch['id']}", headers=op1).json()
    assert done["status"] == "done" and done["summary"]["pairs"] == 0 and done["summary"]["kappa"] is None
    results = client.get(f"{BASE}/blind-reviews/{batch['id']}/results", headers=op1).json()
    assert len(results) == 6 and {r["status"] for r in results} == {"agreed"}
    reused = next(r for r in results if r["item_id"] == task["item_id"])
    with session_factory() as db:
        assert db.query(Annotation).filter_by(capture_point_id=point).count() == 1  # 复用，不重复建
        assert db.get(Annotation, reused["annotation_id"]).annotator_name == "开放复核人"
