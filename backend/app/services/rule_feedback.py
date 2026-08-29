"""规则线 L1 燃料统计：从建议采纳/驳回 + 复核标注聚合每规则的健康度报告。

产出供起草 Agent 分析：哪条规则被频繁驳回（过严/误报）、哪条采纳率高（可靠）、
哪些标注与建议方向矛盾（漏报信号）。

查询统一走 ORM filter_by(kwargs)——关键字即绑定参数（与 agent_tools.py 同风格，
已通过安全审计），无字符串拼 SQL。
"""
from sqlalchemy.orm import Session

from app.models import Advice, Annotation, CapturePoint

# 与规则引擎胁迫检出语义对齐的标签映射：
# 标注为这些 label 时，预期该点应有胁迫类规则命中（否则=漏报信号）
STRESS_LABELS = ("dry_stress", "suspected_disease")
STRESS_RULE_KEY = "R-WHEAT-STRESS-PATCH"


def collect_rule_feedback(db: Session) -> dict:
    """每规则反馈统计 + 全局矛盾信号。"""
    advices = db.query(Advice).all()

    per_rule: dict[str, dict] = {}
    for a in advices:
        entry = per_rule.setdefault(a.rule_key, {
            "rule_key": a.rule_key,
            "tier": (a.rule_snapshot or {}).get("tier"),
            "source": (a.rule_snapshot or {}).get("source"),
            "suggested": 0, "accepted": 0, "rejected": 0,
        })
        entry[a.status] = entry.get(a.status, 0) + 1

    rules = []
    for entry in per_rule.values():
        decided = entry["accepted"] + entry["rejected"]
        entry["reject_rate"] = round(entry["rejected"] / decided, 3) if decided else None
        rules.append(entry)
    rules.sort(key=lambda r: -(r["rejected"] * 2 + r["suggested"]))  # 驳回多的排前

    # 漏报信号：人工标注为胁迫类、但该点没有胁迫类规则命中也没有 high 建议
    stress_annotations = db.query(Annotation).filter_by(label=STRESS_LABELS[0]).all()
    stress_annotations += db.query(Annotation).filter_by(label=STRESS_LABELS[1]).all()
    stress_point_ids = {a.capture_point_id for a in stress_annotations}

    gaps = 0
    for pid in stress_point_ids:
        stress_n = len(db.query(Advice).filter_by(capture_point_id=pid, rule_key=STRESS_RULE_KEY).all())
        high_n = len(db.query(Advice).filter_by(capture_point_id=pid, priority="high").all())
        point = db.get(CapturePoint, pid)
        if point is not None and stress_n == 0 and high_n == 0:
            gaps += 1

    total_points = db.query(CapturePoint).count()
    reviewed_points = len({
        a.capture_point_id for a in db.query(Annotation).all()
    })

    return {
        "rules": rules,
        "global": {
            "total_advices": len(advices),
            "total_annotations": len(db.query(Annotation).all()),
            "reviewed_points": reviewed_points,
            "total_points": total_points,
            "stress_advice_gaps": gaps,
        },
    }
