"""CRUD 接口测试夹具：内存 SQLite + 依赖覆盖，互不污染。"""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def client():
    # 延迟导入：保持 test_health「先设环境变量再导入」的语义不被破坏
    from app.core.db import Base, get_db
    from app.main import app

    engine = create_engine(
        "sqlite://",  # 每个用例独立的内存库
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    TestSession = sessionmaker(bind=engine, autocommit=False, autoflush=False)

    def _override_get_db():
        db = TestSession()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = _override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()
