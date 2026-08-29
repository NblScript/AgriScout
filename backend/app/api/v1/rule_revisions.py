"""规则线 L1 API：燃料查看、起草触发、影子运行、审批（批准才写规则表）。"""
import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.core.db import get_db
from app.models import Patrol, Rule, RuleRevision
from app.schemas.rule import RuleOut
from app.schemas.rule_revision import DraftGenerateOut, RevisionDecideIn, RevisionOut
from app.services.agent_rule_draft import draft_rule_revisions
from app.services.rule_feedback import collect_rule_feedback
from app.services.shadow_run import run_shadow

router = APIRouter(tags=["rule-revisions"])


@router.get("/rule-feedback")
def get_rule_feedback(db: Session = Depends(get_db)):
    """规则健康度报告（起草燃料，供人工参考）。"""
    return collect_rule_feedback(db)


@router.post("/rule-revisions/generate", response_model=DraftGenerateOut)
def generate_drafts(db: Session = Depends(get_db)):
    """触发起草 Agent：分析反馈统计产出修订案（status=draft，不影响现规则）。"""
    try:
        result = draft_rule_revisions(db)
    except ValueError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"LLM 上游错误：{exc}") from exc
    return {
        "created": result["created"],
        "revision_ids": [r.id for r in result["revisions"]],
    }


@router.get("/rule-revisions", response_model=list[RevisionOut])
def list_revisions(
    status: str | None = Query(None),
    limit: int = Query(50, ge=1, le=200),
    db: Session = Depends(get_db),
):
    stmt = db.query(RuleRevision)
    if status:
        stmt = stmt.filter(RuleRevision.status == status)
    return stmt.order_by(RuleRevision.created_at.desc()).limit(limit).all()


@router.post("/rule-revisions/{revision_id}/shadow", response_model=RevisionOut)
def shadow(
    revision_id: int,
    sample_size: int = Query(3, ge=1, le=10),
    db: Session = Depends(get_db),
):
    """对修订案执行影子运行：取最近 N 场已分析巡检做新旧规则 diff。"""
    revision = db.get(RuleRevision, revision_id)
    if revision is None:
        raise HTTPException(status_code=404, detail="修订案不存在")
    if revision.status != "draft":
        raise HTTPException(status_code=422, detail="仅 draft 状态可执行影子运行")
    patrols = (
        db.query(Patrol)
        .filter(Patrol.analysis_status == "done")
        .order_by(Patrol.started_at.desc())
        .limit(sample_size).all()
    )
    if not patrols:
        raise HTTPException(status_code=422, detail="无已分析的历史巡检可做影子运行")
    run_shadow(db, revision, [p.id for p in patrols])
    return revision


@router.post("/rule-revisions/{revision_id}/approve", response_model=RevisionOut)
def approve_revision(revision_id: int, payload: RevisionDecideIn, db: Session = Depends(get_db)):
    """批准修订案：写入规则表（version+1，sync_rules 同款指纹语义）。"""
    revision = db.get(RuleRevision, revision_id)
    if revision is None:
        raise HTTPException(status_code=404, detail="修订案不存在")
    if revision.status != "draft":
        raise HTTPException(status_code=422, detail="该修订案已决策")
    if revision.shadow_result is None:
        raise HTTPException(status_code=422, detail="请先执行影子运行再批准")

    rule = db.query(Rule).filter_by(rule_key=revision.rule_key).one_or_none()
    draft = revision.draft
    if revision.action == "deactivate":
        if rule is None:
            raise HTTPException(status_code=422, detail="目标规则不存在，无法停用")
        rule.active = False
        revision.applied_version = rule.version
    elif revision.action == "add":
        if rule is not None:
            raise HTTPException(status_code=409, detail="规则已存在，不能以 add 方式批准")
        rule = Rule(
            rule_key=draft.get("rule_key", revision.rule_key),
            tier=draft.get("tier", "threshold"),
            condition=draft.get("condition", {}),
            action=draft.get("action", ""),
            params=draft.get("params"),
            priority=draft.get("priority", "medium"),
            active=True,
            source=draft.get("source"),
        )
        db.add(rule)
        db.flush()
        revision.applied_version = rule.version
    else:  # modify
        if rule is None:
            raise HTTPException(status_code=422, detail="目标规则不存在，无法修改")
        for field in ("tier", "priority", "condition", "action", "params", "source"):
            if field in draft:
                setattr(rule, field, draft[field])
        rule.version += 1
        rule.active = True
        revision.applied_version = rule.version

    revision.status = "approved"
    revision.decided_by = payload.decided_by
    revision.decide_note = payload.note
    db.commit()
    db.refresh(revision)
    return revision


@router.post("/rule-revisions/{revision_id}/reject", response_model=RevisionOut)
def reject_revision(revision_id: int, payload: RevisionDecideIn, db: Session = Depends(get_db)):
    """驳回修订案：归档留痕，不写规则表。"""
    revision = db.get(RuleRevision, revision_id)
    if revision is None:
        raise HTTPException(status_code=404, detail="修订案不存在")
    if revision.status != "draft":
        raise HTTPException(status_code=422, detail="该修订案已决策")
    revision.status = "rejected"
    revision.decided_by = payload.decided_by
    revision.decide_note = payload.note
    db.commit()
    db.refresh(revision)
    return revision


@router.get("/rule-revisions/{revision_id}/rule", response_model=list[RuleOut])
def current_rule_state(revision_id: int, db: Session = Depends(get_db)):
    """查看修订案目标规则的当前形态（审批页对比用）。"""
    revision = db.get(RuleRevision, revision_id)
    if revision is None:
        raise HTTPException(status_code=404, detail="修订案不存在")
    rules = db.query(Rule).filter_by(rule_key=revision.rule_key).all()
    return rules
