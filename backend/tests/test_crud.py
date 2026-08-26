"""M1 基础管理 CRUD 接口测试。"""
import pytest

FIELD = {
    "name": "北坡一号地",
    "boundary": {
        "type": "Polygon",
        "coordinates": [
            [[116.10, 39.10], [116.12, 39.10], [116.12, 39.12], [116.10, 39.12], [116.10, 39.10]]
        ],
    },
    "area_ha": 2.0,
    "soil_type": "壤土",
}

CROP = {
    "name": "冬小麦",
    "variety": "济麦22",
    "lifecycle_days": 240,
    "stages": [
        {"name": "出苗期", "days": 15},
        {"name": "分蘖期", "days": 30},
        {"name": "拔节期", "days": 25},
        {"name": "抽穗期", "days": 20},
        {"name": "灌浆期", "days": 35},
        {"name": "成熟期", "days": 115},
    ],
}

DEVICE = {"code": "sim-001", "name": "模拟巡检车", "type": "rover", "model": "SimRover v0"}


def _create_planting(client):
    field_id = client.post("/api/v1/fields", json=FIELD).json()["id"]
    crop_id = client.post("/api/v1/crops", json=CROP).json()["id"]
    resp = client.post(
        "/api/v1/plantings",
        json={"field_id": field_id, "crop_id": crop_id, "sowing_date": "2026-10-15"},
    )
    assert resp.status_code == 201
    return field_id, crop_id, resp.json()


def test_field_crud(client):
    # 创建
    resp = client.post("/api/v1/fields", json=FIELD)
    assert resp.status_code == 201
    body = resp.json()
    assert body["id"] > 0 and body["name"] == FIELD["name"]
    assert body["boundary"]["type"] == "Polygon"

    # 名称重复 → 409
    assert client.post("/api/v1/fields", json=FIELD).status_code == 409

    # 列表与详情
    assert len(client.get("/api/v1/fields").json()) == 1
    got = client.get(f"/api/v1/fields/{body['id']}")
    assert got.status_code == 200 and got.json()["soil_type"] == "壤土"

    # 部分更新
    patched = client.patch(f"/api/v1/fields/{body['id']}", json={"area_ha": 2.5})
    assert patched.json()["area_ha"] == 2.5 and patched.json()["name"] == FIELD["name"]

    # 不存在 → 404
    assert client.get("/api/v1/fields/999").status_code == 404


def test_field_invalid_boundary_rejected(client):
    bad = {**FIELD, "name": "坏边界", "boundary": {"type": "Point", "coordinates": [1, 2]}}
    resp = client.post("/api/v1/fields", json=bad)
    assert resp.status_code == 422
    assert "Polygon" in resp.text


def test_crop_crud(client):
    resp = client.post("/api/v1/crops", json=CROP)
    assert resp.status_code == 201
    body = resp.json()
    assert body["lifecycle_days"] == 240 and len(body["stages"]) == 6
    assert client.post("/api/v1/crops", json=CROP).status_code == 409

    listed = client.get("/api/v1/crops").json()
    assert listed[0]["stages"][0] == {"name": "出苗期", "days": 15}


def test_device_crud_and_status_flow(client):
    resp = client.post("/api/v1/devices", json=DEVICE)
    assert resp.status_code == 201 and resp.json()["status"] == "idle"
    assert client.post("/api/v1/devices", json=DEVICE).status_code == 409

    updated = client.patch("/api/v1/devices/1", json={"status": "active"})
    assert updated.json()["status"] == "active"

    deleted = client.delete("/api/v1/devices/1")
    assert deleted.status_code == 204
    assert client.get("/api/v1/devices").json() == []


def test_planting_full_flow(client):
    field_id, crop_id, planting = _create_planting(client)

    # 关联名称回显（selectinload 属性）
    assert planting["field_name"] == FIELD["name"]
    assert planting["crop_name"] == CROP["name"]
    assert planting["status"] == "active"

    # 过滤查询
    by_field = client.get(f"/api/v1/plantings?field_id={field_id}").json()
    by_crop = client.get(f"/api/v1/plantings?crop_id={crop_id}&status=active").json()
    none = client.get("/api/v1/plantings?field_id=999").json()
    assert len(by_field) == 1 and len(by_crop) == 1 and none == []

    # 引用不存在的外键 → 404
    missing = client.post(
        "/api/v1/plantings", json={"field_id": 999, "crop_id": crop_id, "sowing_date": "2026-10-15"}
    )
    assert missing.status_code == 404


def test_delete_protection_chain(client):
    field_id, crop_id, planting = _create_planting(client)

    # 有种植记录的地块/作物不可删 → 409
    assert client.delete(f"/api/v1/fields/{field_id}").status_code == 409
    assert client.delete(f"/api/v1/crops/{crop_id}").status_code == 409

    # 删除种植记录后解除保护
    assert client.delete(f"/api/v1/plantings/{planting['id']}").status_code == 204
    assert client.delete(f"/api/v1/fields/{field_id}").status_code == 204
    assert client.delete(f"/api/v1/crops/{crop_id}").status_code == 204


def test_health_still_ok(client):
    data = client.get("/api/v1/health").json()
    assert data["status"] == "ok" and data["database"] == "ok"


if __name__ == "__main__":
    pytest.main([__file__])
