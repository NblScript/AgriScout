"""Advice 建议：生成、巡检维度列表、状态管理（采纳/驳回）。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import case, func, select
from sqlalchemy.orm import Session, selectinload

from app.api.deps import paged, patrol_or_404
from app.core.db import get_db
from app.models import Advice
from app.schemas.advice import AdviceOut, AdviceStatusUpdate, GenerateAdvicesOut
from app.schemas.common import Page
from app.services.advice import generate_advices_for_patrol

router = APIRouter(tags=["advices"])




@router.post("/patrols/{patrol_id}/advices/generate", response_model=GenerateAdvicesOut)
def generate_advices(patrol_id: int, db: Session = Depends(get_db)):
    """为巡检生成/重生成建议。

    幂等：只清理 suggested；accepted/rejected 是人工决策事实，永不覆盖，
    且被驳回的 (点, 规则) 组合不再重复建议。
    """
    patrol_or_404(db, patrol_id)
    try:
        result = generate_advices_for_patrol(db, patrol_id)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:  # 规则条件配置错误
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {"patrol_id": patrol_id, **result}


@router.get("/patrols/{patrol_id}/advices", response_model=Page[AdviceOut])
def list_advices(
    patrol_id: int,
    status: str | None = Query(None),
    capture_point_id: int | None = Query(None),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
    db: Session = Depends(get_db),
):
    patrol_or_404(db, patrol_id)
    stmt = (
        select(Advice)
        .options(selectinload(Advice.capture_point))
        .where(Advice.patrol_id == patrol_id)
    )
    if status is not None:
        stmt = stmt.where(Advice.status == status)
    if capture_point_id is not None:
        stmt = stmt.where(Advice.capture_point_id == capture_point_id)

    weight = case(
        (Advice.priority == "high", 3),
        (Advice.priority == "medium", 2),
        else_=1,
    )
    return paged(
        db, stmt, skip, limit,
        order_by=[weight.desc(), Advice.created_at.desc(), Advice.id.desc()],
    )


@router.patch("/advices/{advice_id}", response_model=AdviceOut)
def update_advice_status(advice_id: int, payload: AdviceStatusUpdate, db: Session = Depends(get_db)):
    """采纳/驳回建议——这些决策同时是自我优化闭环的反馈信号（docs/05）。"""
    advice = db.get(Advice, advice_id)
    if advice is None:
        raise HTTPException(status_code=404, detail="建议不存在")
    advice.status = payload.status
    db.commit()
    db.refresh(advice)
    return advice