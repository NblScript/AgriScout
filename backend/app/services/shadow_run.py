"""规则线 L1：影子运行——修订案在历史巡检上与现规则集对比，产出 diff 报告。

内存中模拟（不写 advices 表）：对每场样本巡检，分别统计旧规则集与新规则集
会命中哪些建议，按 (点, rule_key) 聚合出 added/removed/changed。
diff 写回 rule_revisions.shadow_result 供人工审批参考。
"""
from sqlalchemy.orm import Session

from app.models import Advice, Rule, RuleRevision
from app.services.advice import generate_advices_for_patrol


def _rule_key_set(db: Session, patrol_id: int) -> set[tuple[int, str]]:
    """该巡检当前建议的 (capture_point_id, rule_key) 集合（= 旧规则集的结果）。"""
    advices = db.query(Advice).filter_by(patrol_id=patrol_id).all()
    return {(a.capture_point_id, a.rule_key) for a in advices if a.capture_point_id}


def run_shadow(db: Session, revision: RuleRevision, sample_patrol_ids: list[int]) -> dict:
    """对修订案执行影子运行，写回 shadow_result。

    实现：把 draft 应用到内存中的规则查询结果上（对 modify=改字段后重匹配、
    deactivate=视为消失、add=多一条规则参与匹配），对比新旧 (点, 规则) 集合。

    为保证确定性：临时把 Rule 表按 draft 修改 → 重算建议集合 → 回滚。
    用真实 savepoint 包裹，任何异常不落库。
    """
    before_sets: dict[int, set] = {}
    for pid in sample_patrol_ids:
        before_sets[pid] = _rule_key_set(db, pid)

    began = False
    try:
        db.begin_nested()  # savepoint
        began = True
        _apply_draft_to_rules(db, revision)
        after_sets: dict[int, set] = {}
        for pid in sample_patrol_ids:
            # 内存重算（generate_advices 会写 advices 表——用 savepoint 保证可回滚）
            generate_advices_for_patrol(db, pid)
            after_sets[pid] = _rule_key_set(db, pid)
        db.rollback()
        began = False
    finally:
        if began:
            db.rollback()

    added: list[str] = []
    removed: list[str] = []
    per_patrol = []
    for pid in sample_patrol_ids:
        before, after = before_sets[pid], after_sets.get(pid, set())
        p_added = after - before
        p_removed = before - after
        added += [f"p{pid}:{k}" for _pt, k in p_added]
        removed += [f"p{pid}:{k}" for _pt, k in p_removed]
        per_patrol.append({
            "patrol_id": pid,
            "before": len(before), "after": len(after),
            "added": len(p_added), "removed": len(p_removed),
        })

    result = {
        "patrols_checked": sample_patrol_ids,
        "added_total": len(added),
        "removed_total": len(removed),
        "added_sample": sorted(added)[:20],
        "removed_sample": sorted(removed)[:20],
        "per_patrol": per_patrol,
    }
    revision.shadow_result = result
    db.commit()
    db.refresh(revision)
    return result


def _apply_draft_to_rules(db: Session, revision: RuleRevision) -> None:
    """在当前事务（savepoint 内）把 draft 应用到 Rule 表；由调用方回滚。"""
    rule = db.query(Rule).filter_by(rule_key=revision.rule_key).one_or_none()
    if revision.action == "deactivate":
        if rule:
            rule.active = False
        return
    draft = revision.draft
    if revision.action == "add" and rule is None:
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
        return
    if rule is None:
        return
    # modify
    for field in ("tier", "priority", "condition", "action", "params", "source"):
        if field in draft:
            setattr(rule, field, draft[field])
    rule.active = True
    db.flush()
