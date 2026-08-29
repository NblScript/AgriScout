"""规则线 L1：起草 Agent——燃料统计 + 当前规则 → LLM 产出修订案（仅起草）。

红线：Agent 不写规则表。产出存 rule_revisions（status=draft），
生效必须走 影子运行 + 人工审批（services/shadow_run.py + API approve）。
"""
import json
from pathlib import Path

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.models import Rule, RuleRevision
from app.services.llm_report import PROMPTS_DIR, _chat
from app.services.rule_feedback import collect_rule_feedback

DRAFT_MAX_CHARS = 16000


def _current_rules_yaml_like(db: Session) -> list[dict]:
    rules = db.query(Rule).filter_by(active=True).all()
    return [{
        "rule_key": r.rule_key, "tier": r.tier, "priority": r.priority,
        "condition": r.condition, "action": r.action, "params": r.params,
        "source": r.source, "version": r.version,
    } for r in rules]


def draft_rule_revisions(db: Session) -> dict:
    """燃料 + 当前规则 → LLM 起草修订案（可 0-N 条），全部落 rule_revisions。

    返回 {"created": n, "revisions": [RuleRevision]}；
    LLM 未配置抛 ValueError（→503），上游错误抛 httpx.HTTPError（→502）。
    """
    settings = get_settings()
    if not settings.llm_enabled:
        raise ValueError("未配置 LLM：请在 backend/.env 设置 LLM_API_BASE / LLM_API_KEY / LLM_MODEL")

    feedback = collect_rule_feedback(db)
    current = _current_rules_yaml_like(db)

    prompt_path = sorted(PROMPTS_DIR.glob("rule_draft_v*.md"))[-1]
    system = prompt_path.read_text(encoding="utf-8")
    user = json.dumps({
        "feedback": feedback,
        "current_rules": current,
        "output_contract": "只输出 JSON 数组，每项含 action(modify|add|deactivate)、rule_key、draft、reason",
    }, ensure_ascii=False, default=str)[:DRAFT_MAX_CHARS]

    raw = _chat(system, user)
    drafts = _parse_drafts(raw)

    created = []
    for item in drafts:
        if item.get("action") not in ("modify", "add", "deactivate"):
            continue
        if not item.get("rule_key") or not isinstance(item.get("draft"), dict):
            continue
        rev = RuleRevision(
            rule_key=item["rule_key"],
            action=item["action"],
            draft=item["draft"],
            reason=str(item.get("reason", ""))[:2000],
            model=settings.llm_model,
            prompt_version=prompt_path.stem.removeprefix("rule_draft_"),
        )
        db.add(rev)
        created.append(rev)
    db.commit()
    for r in created:
        db.refresh(r)
    return {"created": len(created), "revisions": created}


def _parse_drafts(raw: str) -> list[dict]:
    """解析 LLM 输出：容忍 markdown 代码块包裹；解析失败返回空（宁缺勿滥）。"""
    text = raw.strip()
    if text.startswith("```"):
        text = text.strip("`")
        if text.startswith("json"):
            text = text[4:]
    start, end = text.find("["), text.rfind("]")
    if start == -1 or end == -1 or end <= start:
        return []
    try:
        parsed = json.loads(text[start:end + 1])
        return parsed if isinstance(parsed, list) else []
    except json.JSONDecodeError:
        return []
