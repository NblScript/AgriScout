"""API 层公共助手：404 依赖与分页样板（消除 5 处重复定义）。"""
from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import Patrol
from app.schemas.common import Page

TypeVarItem = None  # 占位：Python 泛型在运行时由 Page[T] 承担


def patrol_or_404(db: Session, patrol_id: int) -> Patrol:
    patrol = db.get(Patrol, patrol_id)
    if patrol is None:
        raise HTTPException(status_code=404, detail="巡检任务不存在")
    return patrol


def paged(db: Session, stmt, skip: int, limit: int, order_by=None) -> Page:
    """统一分页：total(subquery count) + offset/limit，返回 Page 信封。

    order_by：可选排序子句（在 offset 前应用）。
    """
    total = db.scalar(select(func.count()).select_from(stmt.subquery())) or 0
    if order_by is not None:
        stmt = stmt.order_by(*order_by)
    rows = db.scalars(stmt.offset(skip).limit(limit)).all()
    return Page(items=list(rows), total=total, skip=skip, limit=limit)
