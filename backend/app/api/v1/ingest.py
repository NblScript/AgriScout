"""数据接入端点：采集端（小车/模拟器）唯一入口。"""
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db, get_session_factory
from app.schemas.patrol import IngestResultOut, PatrolPackageIn
from app.services.analysis import Analyzer, get_analyzer
from app.services.analysis.runner import run_patrol_analysis
from app.services.ingest import DuplicateError, ingest_patrol_package
from app.services.storage import Storage, get_storage

router = APIRouter(prefix="/ingest", tags=["ingest"])


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
    return result
