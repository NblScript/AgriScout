"""Rule 规则管理 CRUD + YAML 同步入口。"""
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import ValidationError
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
    # 合并后整体再过一遍 RuleCreate：单字段合法不代表组合合法（如 tier 改 routine 但条件含天气）。
    # 不校验就落库会让 RuleOut 序列化失败，GET /rules 整表 500。
    merged = {
        "rule_key": obj.rule_key, "crop_id": obj.crop_id, "tier": obj.tier,
        "condition": obj.condition, "action": obj.action, "params": obj.params,
        "priority": obj.priority, "source": obj.source,
    }
    merged.update({k: v for k, v in changes.items() if k in merged})
    try:
        RuleCreate(**merged)
    except ValidationError as exc:
        raise HTTPException(
            status_code=422, detail=f"修改后的规则不合法：{exc.errors()[0].get('msg', exc)}",
        ) from exc
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
def trigger_yaml_sync(
    force: bool = Query(False, description="以 YAML 覆盖审批修订案产生的规则版本"),
    db: Session = Depends(get_db),
):
    """从 backend/rules/*.yaml 幂等同步种子规则；与审批结果冲突的规则跳过并列入 conflicts。"""
    if not Path(RULES_DIR).exists():
        raise HTTPException(status_code=404, detail=f"规则目录不存在：{RULES_DIR}")
    return sync_rules(db, force=force)
