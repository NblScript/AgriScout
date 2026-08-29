"""规则修订案的生效逻辑：approve 时把 draft 写入规则表（唯一合法入口）。

与影子运行的区别：影子只在内存构造 draft 视图（shadow_run._draft_rule_view），
本模块才真正落库——起草权（Agent）与生效权（人工批准后此处执行）分离的落点。
"""
from sqlalchemy.orm import Session

from app.models import Rule, RuleRevision


def apply_draft_to_rule(db: Session, revision: RuleRevision) -> int:
    """把已批准的修订案写入规则表，返回应用后的规则 version。

    调用方保证：revision.status 即将置为 approved、shadow 已跑、审计字段由其填写。
    add：规则必须不存在；modify：必须存在且 version+1；deactivate：软下线不改版本。
    违反前置条件抛 ValueError（路由映射 422/409）。
    """
    rule = db.query(Rule).filter_by(rule_key=revision.rule_key).one_or_none()
    draft = revision.draft

    if revision.action == "deactivate":
        if rule is None:
            raise ValueError(f"目标规则 {revision.rule_key} 不存在，无法停用")
        rule.active = False
        return rule.version

    if revision.action == "add":
        if rule is not None:
            raise ValueError(f"规则 {revision.rule_key} 已存在，不能以 add 方式批准")
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
        return rule.version

    # modify
    if rule is None:
        raise ValueError(f"目标规则 {revision.rule_key} 不存在，无法修改")
    for field in ("tier", "priority", "condition", "action", "params", "source"):
        if field in draft:
            setattr(rule, field, draft[field])
    rule.version += 1
    rule.active = True
    return rule.version
