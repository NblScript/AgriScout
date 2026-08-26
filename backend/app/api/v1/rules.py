"""Rule 规则管理 CRUD + YAML 同步入口。"""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import Rule
from app.schemas.rule import RuleCreate, RuleOut, RuleUpdate
from app.tools.sync_rules import RULES_DIR, sync_rules

router = APIRouter(prefix="/rules", tags=["rules"])

# 内容字段变更才升版本；active 开关不算内容变更
_VERSIONED_FIELDS = {"tier", "condition", "action", "params", "priority", "source", "crop_id"}


@router.get("", response_model=list[RuleOut])
def list_rules(
    crop_id: int | None = None,
    tier: str | None = Query(None),
    active: bool | None = Query(None),
    db: Session = Depends(get_db),
):
    stmt = select(Rule)
    if crop_id is not None:
        stmt = stmt.where(Rule.crop_id == crop_id)
    if tier is not None:
        stmt = stmt.where(Rule.tier == tier)
    if active is not None:
        stmt = stmt.where(Rule.active.is_(active))
    return list(db.scalars(stmt.order_by(Rule.tier, Rule.rule_key)).all())


@router.post("", response_model=RuleOut, status_code=201)
def create_rule(payload: RuleCreate, db: Session = Depends(get_db)):
    obj = Rule(**payload.model_dump())
    db.add(obj)
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status_code=409, detail=f"rule_key 已存在：{payload.rule_key}") from exc
    db.refresh(obj)
    return obj


@router.get("/{rule_id}", response_model=RuleOut)
def get_rule(rule_id: int, db: Session = Depends(get_db)):
    obj = db.get(Rule, rule_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="规则不存在")
    return obj


@router.patch("/{rule_id}", response_model=RuleOut)
def update_rule(rule_id: int, payload: RuleUpdate, db: Session = Depends(get_db)):
    obj = db.get(Rule, rule_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="规则不存在")
    changes = payload.model_dump(exclude_unset=True)
    before = {f: getattr(obj, f) for f in _VERSIONED_FIELDS}
    for key, value in changes.items():
        setattr(obj, key, value)
    if any(before.get(f) != getattr(obj, f) for f in _VERSIONED_FIELDS):
        obj.version += 1  # 内容变更 → 版本自增（进后续 rule_snapshot）
    db.commit()
    db.refresh(obj)
    return obj


@router.delete("/{rule_id}", response_model=RuleOut)
def deactivate_rule(rule_id: int, db: Session = Depends(get_db)):
    """软下线（只停用不删除，docs/05 纪律）：历史 Advice 的快照不受影响。"""
    obj = db.get(Rule, rule_id)
    if obj is None:
        raise HTTPException(status_code=404, detail="规则不存在")
    obj.active = False
    db.commit()
    db.refresh(obj)
    return obj


@router.post("/sync-yaml")
def trigger_yaml_sync(db: Session = Depends(get_db)):
    """从 backend/rules/*.yaml 幂等同步种子规则。"""
    if not Path(RULES_DIR).exists():
        raise HTTPException(status_code=404, detail=f"规则目录不存在：{RULES_DIR}")
    return sync_rules(db)
