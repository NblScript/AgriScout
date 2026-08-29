"""规则线 L1：影子运行——修订案在历史巡检上与现规则集对比，产出 diff 报告。

实现为纯计算：用 advice.compute_advice_pairs（只读零写入）分别求
"现规则集命中集合" 与 "draft 应用后的规则集命中集合"，差集即影子 diff。
没有任何写操作——历史上曾用 savepoint + 重算落库，但内部 commit 会击穿
savepoint 造成 draft 泄漏进规则表（P0 事故），已废弃该实现。
"""
from sqlalchemy.orm import Session

from app.models import Rule, RuleRevision
from app.services.advice import compute_advice_pairs


def run_shadow(db: Session, revision: RuleRevision, sample_patrol_ids: list[int]) -> dict:
    """对修订案执行影子运行（只读），写回 revision.shadow_result 并提交。"""
    before_sets: dict[int, set] = {}
    after_sets: dict[int, set] = {}
    for pid in sample_patrol_ids:
        before_sets[pid] = compute_advice_pairs(db, pid)

    # 内存中构造 draft 应用后的规则视图，供纯计算
    draft_rules = _draft_rule_view(db, revision)
    for pid in sample_patrol_ids:
        after_sets[pid] = compute_advice_pairs(db, pid, extra_rules=draft_rules, exclude_keys={revision.rule_key})

    added: list[str] = []
    removed: list[str] = []
    per_patrol = []
    for pid in sample_patrol_ids:
        before, after = before_sets[pid], after_sets[pid]
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


def _draft_rule_view(db: Session, revision: RuleRevision) -> list[Rule]:
    """构造 draft 应用后的内存 Rule 对象列表（不加入 Session，零落库）。

    modify/add → 生成携带 draft 字段的临时 Rule 实例（transient，不 add）；
    deactivate → 返回空列表（该规则从规则集中消失）。
    """
    if revision.action == "deactivate":
        return []
    draft = revision.draft
    rule = Rule(
        rule_key=draft.get("rule_key", revision.rule_key),
        tier=draft.get("tier", "threshold"),
        condition=draft.get("condition", {}),
        action=draft.get("action", ""),
        params=draft.get("params"),
        priority=draft.get("priority", "medium"),
        active=True,
        version=1,
        source=draft.get("source"),
    )
    return [rule]
