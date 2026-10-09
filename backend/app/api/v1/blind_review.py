"""盲法复核接口（计划 0007 P1-9，决策 D25）：建批次、取下一张、判读、汇总与结果。判读人取登录账号。"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.core.deps import CurrentUser, get_current_user
from app.models import BlindReviewBatch, BlindReviewItem, Field
from app.schemas.blind_review import (
    BlindResultOut, BlindReviewCreate, BlindReviewOut, BlindReviewTask, BlindVoteIn, BlindVoteOut,
)
from app.services import blind_review

router = APIRouter(prefix="/blind-reviews", tags=["blind-review"])


def _batch_or_404(db: Session, batch_id: int) -> BlindReviewBatch:
    batch = db.get(BlindReviewBatch, batch_id)
    if batch is None:
        raise HTTPException(status_code=404, detail="盲评批次不存在")
    return batch


def _out(batch: BlindReviewBatch, user: CurrentUser) -> BlindReviewOut:
    return BlindReviewOut.model_validate({
        **{key: getattr(batch, key) for key in (
            "id", "field_id", "name", "status", "seed", "params", "item_count", "created_by", "done_at", "created_at",
        )},
        "summary": blind_review.summarize(batch, user.id),
    })


@router.post("", response_model=BlindReviewOut, status_code=201)
def create_blind_review(payload: BlindReviewCreate, db: Session = Depends(get_db),
                        user: CurrentUser = Depends(get_current_user)):
    if db.get(Field, payload.field_id) is None:
        raise HTTPException(status_code=404, detail="地块不存在")
    try:
        spec = blind_review.BatchSpec(
            field_id=payload.field_id, date_from=payload.date_from, date_to=payload.date_to,
            sample_size=payload.sample_size, seed=payload.seed,
            reference_keys=tuple(key.strip() for key in payload.reference_keys if key.strip()),
            side=payload.side, double_review=payload.double_review,
        )
        batch = blind_review.create_batch(db, spec, name=payload.name.strip(), created_by=user.display_name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    return _out(batch, user)


@router.get("", response_model=list[BlindReviewOut])
def list_blind_reviews(field_id: int | None = Query(None, gt=0), db: Session = Depends(get_db),
                       user: CurrentUser = Depends(get_current_user)):
    stmt = select(BlindReviewBatch).order_by(BlindReviewBatch.created_at.desc(), BlindReviewBatch.id.desc())
    if field_id is not None:
        stmt = stmt.where(BlindReviewBatch.field_id == field_id)
    return [_out(batch, user) for batch in db.scalars(stmt)]


@router.get("/{batch_id}", response_model=BlindReviewOut)
def get_blind_review(batch_id: int, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    return _out(_batch_or_404(db, batch_id), user)


@router.get("/{batch_id}/next", response_model=BlindReviewTask | None)
def next_blind_item(batch_id: int, db: Session = Depends(get_db), user: CurrentUser = Depends(get_current_user)):
    batch = _batch_or_404(db, batch_id)
    nxt = blind_review.next_item(batch, user.id) if user.id is not None else None
    if nxt is None:
        return None
    return BlindReviewTask(
        batch_id=batch.id, item_id=nxt.item.id, position=nxt.item.position, item_count=batch.item_count,
        round=nxt.round, photo_url=nxt.item.capture_point.photo_url, prior_labels=nxt.prior_labels,
    )


@router.post("/{batch_id}/items/{item_id}/votes", response_model=BlindVoteOut, status_code=201)
def vote_blind_item(batch_id: int, item_id: int, payload: BlindVoteIn, db: Session = Depends(get_db),
                    user: CurrentUser = Depends(get_current_user)):
    if user.id is None:
        raise HTTPException(status_code=403, detail="判读要用登录账号，判读人按账号记录")
    batch = _batch_or_404(db, batch_id)
    item = db.get(BlindReviewItem, item_id)
    if item is None or item.batch_id != batch.id:
        raise HTTPException(status_code=404, detail="批次里没有这张照片")
    try:
        blind_review.cast_vote(db, batch, item, user_id=user.id, reviewer_name=user.display_name, label=payload.label)
    except blind_review.ReviewConflict as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        db.rollback()
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    db.commit()
    # 不回传状态和定论：判读人不该从这里得知别人判的是什么
    return BlindVoteOut(item_id=item.id)


@router.get("/{batch_id}/results", response_model=list[BlindResultOut])
def blind_review_results(batch_id: int, db: Session = Depends(get_db)):
    """逐张结论带株号和拍摄时间，全部定论后才给：判读中途看到别人的结论会破坏盲法（同一株在批里有多天的照片）。"""
    batch = _batch_or_404(db, batch_id)
    if batch.status != "done":
        raise HTTPException(status_code=409, detail="这批还没全部定论，定论前不公开逐张结论")
    return [
        BlindResultOut(
            position=item.position, item_id=item.id, capture_point_id=item.capture_point_id,
            patrol_id=item.capture_point.patrol_id, observation_key=item.capture_point.observation_key,
            captured_at=item.capture_point.captured_at, photo_url=item.capture_point.photo_url,
            origin=item.origin, status=item.status, final_label=item.final_label, annotation_id=item.annotation_id,
        )
        for item in batch.items
    ]
