"""规则修订案的生效逻辑：approve 时把 draft 写入规则表（唯一合法入口）。

与影子运行的区别：影子只在内存构造 draft 视图（shadow_run._draft_rule_view），
本模块才真正落库——起草权（Agent）与生效权（人工批准后此处执行）分离的落点。
"""
from sqlalchemy.orm import Session

from app.models import Rule, RuleRevision


_MODIFIABLE_FIELDS = ("tier", "priority", "condition", "action", "params", "source")


def resolve_draft_fields(db: Session, revision: RuleRevision) -> dict:
    """修订案生效后规则的完整字段（影子运行与审批生效共用，保证「影子看到的」=「批准后得到的」）。

    add：draft 即新规则，缺省字段取 RuleCreate 同款默认；crop_id 取 draft 显式值（缺失=全局规则）。
    modify：以现规则为底、draft 中出现的字段覆盖；rule_key/crop_id 沿用现规则。
    旧实现影子用默认值补缺（priority 缺失当 medium）、生效却保留现值，
    草稿省略字段时两者分叉，影子报告的 Top-K 挤出结论会与上线结果不一致。
    deactivate / 目标规则不存在的 modify 返回空字典。
    """
    draft = revision.draft or {}
    if revision.action == "add":
        return {
            "rule_key": revision.rule_key,
            "crop_id": draft.get("crop_id"),
            "tier": draft.get("tier", "threshold"),
            "condition": draft.get("condition", {}),
            "action": draft.get("action", ""),
            "params": draft.get("params"),
            "priority": draft.get("priority", "medium"),
            "source": draft.get("source"),
        }
    if revision.action != "modify":
        return {}
    rule = db.query(Rule).filter_by(rule_key=revision.rule_key).one_or_none()
    if rule is None:
        return {}
    fields = {"rule_key": rule.rule_key, "crop_id": rule.crop_id}
    fields.update({f: getattr(rule, f) for f in _MODIFIABLE_FIELDS})
    fields.update({f: draft[f] for f in _MODIFIABLE_FIELDS if f in draft})
    return fields


def apply_draft_to_rule(db: Session, revision: RuleRevision) -> int:
    """把已批准的修订案写入规则表，返回应用后的规则 version。

    先对「生效后的完整规则」过 RuleCreate 校验（condition 键/算子白名单、routine 层约束）——
    非法组合在此处 422 拒绝，而不是入库后拖垮该作物的建议生成。
    调用方保证：revision.status 即将置为 approved、shadow 已跑、审计字段由其填写。
    add：规则必须不存在；modify：必须存在且 version+1；deactivate：软下线不改版本。
    违反前置条件抛 ValueError（路由映射 422/409）。
    """
    from app.schemas.rule import RuleCreate

    rule = db.query(Rule).filter_by(rule_key=revision.rule_key).one_or_none()

    if revision.action == "deactivate":
        if rule is None:
            raise ValueError(f"目标规则 {revision.rule_key} 不存在，无法停用")
        rule.active = False
        return rule.version

    if revision.action == "add" and rule is not None:
        raise ValueError(f"规则 {revision.rule_key} 已存在，不能以 add 方式批准")
    if revision.action == "modify" and rule is None:
        raise ValueError(f"目标规则 {revision.rule_key} 不存在，无法修改")

    fields = resolve_draft_fields(db, revision)
    try:
        RuleCreate(**fields)
    except Exception as exc:  # noqa: BLE001 pydantic 校验错误转 422 语义
        raise ValueError(f"draft 未通过规则校验：{exc}") from exc

    if revision.action == "add":
        rule = Rule(**fields, active=True)
        db.add(rule)
        db.flush()
        return rule.version

    # modify
    for field in _MODIFIABLE_FIELDS:
        setattr(rule, field, fields[field])
    rule.version += 1
    rule.active = True
    return rule.version
