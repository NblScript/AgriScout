"""数据接入端点：采集端（小车/模拟器）唯一入口。"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.schemas.patrol import IngestResultOut, PatrolPackageIn
from app.services.ingest import DuplicateError, ingest_patrol_package
from app.services.storage import Storage, get_storage

router = APIRouter(prefix="/ingest", tags=["ingest"])


@router.post("/patrol", response_model=IngestResultOut, status_code=201)
def ingest_patrol(
    package: PatrolPackageIn,
    db: Session = Depends(get_db),
    storage: Storage = Depends(get_storage),
):
    """上传巡检包：单事务落库，秒级返回；分析由后台异步执行（M3）。"""
    try:
        return ingest_patrol_package(db, package, storage)
    except DuplicateError as exc:
        raise HTTPException(
            status_code=409,
            detail=f"重复上传：相同地块/设备/开始时间的巡检包已存在（patrol_id={exc.duplicate_id}）",
        ) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
