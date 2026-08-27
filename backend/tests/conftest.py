"""CRUD 接口测试夹具：内存 SQLite + 依赖覆盖，互不污染。"""
import os
from pathlib import Path

# 测试恒用占位引擎：本地 .env 的 ANALYZER_BACKEND=yolo 不得泄漏进测试
# （环境变量优先级高于 .env 文件；须在导入 app 前设置）
os.environ["ANALYZER_BACKEND"] = "placeholder"
# 同理：LLM 配置清空——测试不外呼真实 LLM（报告服务走 monkeypatch _chat）
os.environ["LLM_API_BASE"] = ""
os.environ["LLM_API_KEY"] = ""
os.environ["LLM_MODEL"] = ""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool


@pytest.fixture()
def media_dir(tmp_path) -> Path:
    """测试用照片存储目录（随用例销毁）。"""
    return tmp_path / "media"


@pytest.fixture()
def client(media_dir: Path):
    # 延迟导入：保持 test_health「先设环境变量再导入」的语义不被破坏
    from app.core.db import Base, get_db, get_session_factory
    from app.main import app
    from app.services.storage import LocalStorage, get_storage

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
    app.dependency_overrides[get_session_factory] = lambda: TestSession  # 后台任务也写测试库
    app.dependency_overrides[get_storage] = lambda: LocalStorage(media_dir)
    yield TestClient(app)
    app.dependency_overrides.clear()
