"""健康检查接口测试。"""
from fastapi.testclient import TestClient


def test_health_ok(client):
    """经 client 夹具（内存测试库 + 依赖覆盖）验证健康接口。"""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["app"] == "AgriScout"
    assert data["database"] == "ok"


def test_root_docs_available(client):
    assert client.get("/docs").status_code == 200
