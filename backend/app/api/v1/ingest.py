"""数据接入端点：采集端（小车/模拟器）唯一入口。"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db, get_session_factory
from app.schemas.patrol import IngestResultOut, PatrolPackageIn
from app.services.analysis import Analyzer, get_analyzer
from app.services.analysis.runner import run_patrol_analysis
from app.services.ingest import DuplicateError, ingest_patrol_package
from app.services.storage import Storage, get_storage

import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.get("/patrol-schema")
def patrol_package_schema():
    """导出巡检包协议 JSON Schema——采集端（真车/第三方）的对接合同。"""
    return PatrolPackageIn.model_json_schema()


@router.post("/patrol", response_model=IngestResultOut, status_code=201)
def ingest_patrol(
    package: PatrolPackageIn,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
    analyzer: Analyzer = Depends(get_analyzer),
    session_factory=Depends(get_session_factory),
):
    """上传巡检包：单事务落库秒级返回；逐点分析由后台任务异步执行（M3）。"""
    try:
        result = ingest_patrol_package(db, package, storage)
    except DuplicateError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"重复上传：相同地块/设备/开始时间的巡检包已存在（patrol_id={exc.duplicate_id}）",
        ) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    # 落库成功后调度分析；TestClient 下任务随请求周期同步跑完，便于断言
    background_tasks.add_task(
        run_patrol_analysis, result.patrol_id, analyzer, storage, session_factory,
    )
    # LLM 巡检报告与分析解耦：独立后台任务（LLM 调用可达 120s，
    # 不占分析 worker；未配置 LLM 时任务内部静默跳过）
    background_tasks.add_task(_generate_report_if_enabled, result.patrol_id, session_factory)
    return result


def _generate_report_if_enabled(patrol_id: int, session_factory) -> None:
    """独立报告任务：自建会话（请求已返回）；未配置 LLM 静默返回。"""
    from app.core.config import get_settings

    if not get_settings().llm_enabled:
        return
    db = session_factory()
    try:
        from app.services.llm_report import generate_report

        report = generate_report(db, patrol_id)
        logger.info("patrol %s llm report generated (model=%s)", patrol_id, report.model)
    except Exception:  # noqa: BLE001 报告失败不影响分析/建议结论
        db.rollback()
        logger.warning("patrol %s llm report generation failed", patrol_id, exc_info=True)
    finally:
        db.close()
