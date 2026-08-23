"""健康检查接口测试。"""
import os

from fastapi.testclient import TestClient


def test_health_ok(tmp_path, monkeypatch):
    # 用临时 SQLite，避免污染开发库
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path}/test.db")

    from app.main import app  # 环境变量就绪后再导入

    client = TestClient(app)
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["app"] == "AgriScout"
    assert data["database"] == "ok"


def test_root_docs_available():
    from app.main import app

    client = TestClient(app)
    assert client.get("/docs").status_code == 200
