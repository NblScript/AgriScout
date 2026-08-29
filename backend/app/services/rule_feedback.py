"""规则线 L1 燃料统计：从建议采纳/驳回 + 复核标注聚合每规则的健康度报告。

产出供起草 Agent 分析：哪条规则被频繁驳回（过严/误报）、哪条采纳率高（可靠）、
哪些标注与建议方向矛盾（漏报信号）。

性能：GROUP BY 聚合 + 集合化漏报检查（无全表进内存、无逐点 N+1）。
查询统一走 ORM query API（关键字/绑定参数，与 agent_tools.py 同风格）。
"""
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import Advice, Annotation, CapturePoint

# 与规则引擎胁迫检出语义对齐的标签映射：
# 标注为这些 label 时，预期该点应有胁迫类规则命中（否则=漏报信号）
STRESS_LABELS = ("dry_stress", "suspected_disease")
STRESS_RULE_KEY = "R-WHEAT-STRESS-PATCH"


def collect_rule_feedback(db: Session) -> dict:
    """每规则反馈统计 + 全局矛盾信号。"""
    grouped = (
        db.query(Advice.rule_key, Advice.status, func.count())
        .group_by(Advice.rule_key, Advice.status)
        .all()
    )

    # tier/source 取该规则最新一条建议的快照
    meta_by_key: dict[str, dict] = {}
    latest_rows = (
        db.query(Advice)
        .order_by(Advice.created_at.desc(), Advice.id.desc())
        .limit(200)
        .all()
    )
    for a in latest_rows:
        if a.rule_key not in meta_by_key and a.rule_snapshot:
            meta_by_key[a.rule_key] = {
                "tier": a.rule_snapshot.get("tier"),
                "source": a.rule_snapshot.get("source"),
            }

    status_by_key: dict[str, dict[str, int]] = {}
    total_advices = 0
    for rule_key, status, n in grouped:
        status_by_key.setdefault(rule_key, {})[status] = n
        total_advices += n

    rules = []
    for rule_key, counts in status_by_key.items():
        suggested = counts.get("suggested", 0)
        accepted = counts.get("accepted", 0)
        rejected = counts.get("rejected", 0)
        decided = accepted + rejected
        meta = meta_by_key.get(rule_key, {})
        rules.append({
            "rule_key": rule_key,
            "tier": meta.get("tier"),
            "source": meta.get("source"),
            "suggested": suggested,
            "accepted": accepted,
            "rejected": rejected,
            "reject_rate": round(rejected / decided, 3) if decided else None,
        })
    rules.sort(key=lambda r: -(r["rejected"] * 2 + r["suggested"]))  # 驳回多的排前

    # 漏报信号：标注为胁迫类的存量点位中，既无胁迫规则命中也无 high 建议的数量
    # （三次轻量取 ID 集合做集合运算，避免逐点 N+1）
    stress_point_ids: set[int] = set()
    for label in STRESS_LABELS:
        rows = db.query(Annotation.capture_point_id).filter_by(label=label).all()
        stress_point_ids.update(r[0] for r in rows if r[0] is not None)

    gaps = 0
    if stress_point_ids:
        with_stress = {
            r[0] for r in db.query(Advice.capture_point_id)
            .filter_by(rule_key=STRESS_RULE_KEY).all() if r[0] is not None
        }
        with_high = {
            r[0] for r in db.query(Advice.capture_point_id)
            .filter_by(priority="high").all() if r[0] is not None
        }
        all_point_ids = {
            r[0] for r in db.query(CapturePoint.id).all()
        }
        gaps = len(stress_point_ids & all_point_ids - with_stress - with_high)

    total_points = db.query(CapturePoint).count()
    reviewed_rows = db.query(Annotation.capture_point_id).all()
    reviewed_points = len({r[0] for r in reviewed_rows if r[0] is not None})
    total_annotations = db.query(Annotation).count()

    return {
        "rules": rules,
        "global": {
            "total_advices": total_advices,
            "total_annotations": total_annotations,
            "reviewed_points": reviewed_points,
            "total_points": total_points,
            "stress_advice_gaps": gaps,
        },
    }
