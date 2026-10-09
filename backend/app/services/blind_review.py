"""盲法复核（计划 0007 P1-9，决策 D25）：独立测试集的标签在看不到模型输出的情况下判读，分歧二次判读。

申报书 8.2：界面隐藏模型预测、选样原因和策略标签；设随机抽查和固定参考，低风险也要核查。
- 抽样：一个棚、一段田间日期里的合格照片，按种子随机抽 N 张，再加固定参考株在范围内的全部合格照片，打乱顺序；
- 判读：默认两人独立判读，一致即定，不一致由第三人看过两个判读（不显示是谁）后定论；也可设为单人判读；
- 定论写成该照片的标注（同标签已有则复用），批次记下标注编号，数据集可只收某批次的盲评结论（D24 的 source_filter）。
抽样和一致性统计是纯函数；写库的函数只做状态机和落标注。
"""
from __future__ import annotations

import hashlib
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timezone
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.timeutil import field_date
from app.models import Annotation, BlindReviewBatch, BlindReviewItem, BlindReviewVote, CapturePoint, Patrol

BLIND_LABELS = ("normal", "downy_mildew_early", "downy_mildew_symptomatic", "other")
SIDES = ("under", "any")
MAX_SAMPLE = 500
MAX_ITEMS = 1000
RESOLVED = ("agreed", "adjudicated")


class ReviewConflict(Exception):
    """判读与当前状态冲突（已判过、已定论、轮次已满）：接口映射为 409。"""


@dataclass(frozen=True)
class BatchSpec:
    """建批次的参数；全部写进批次的 ``params`` 留档。"""

    field_id: int
    date_from: date
    date_to: date
    sample_size: int
    seed: int = 0
    reference_keys: tuple[str, ...] = ()
    side: str = "under"
    double_review: bool = True

    def __post_init__(self) -> None:
        if self.date_from > self.date_to:
            raise ValueError("起始日期不能晚于结束日期")
        if not 0 <= self.sample_size <= MAX_SAMPLE:
            raise ValueError(f"随机抽样张数必须在 0 到 {MAX_SAMPLE} 之间")
        if self.side not in SIDES:
            raise ValueError(f"side 只能是 {'、'.join(SIDES)}")
        if self.sample_size == 0 and not self.reference_keys:
            raise ValueError("随机抽样张数为 0 时必须给出固定参考株")

    def params(self) -> dict[str, Any]:
        return {
            "date_from": self.date_from.isoformat(), "date_to": self.date_to.isoformat(),
            "sample_size": self.sample_size, "reference_keys": sorted(set(self.reference_keys)),
            "side": self.side, "double_review": self.double_review,
        }


@dataclass(frozen=True)
class Candidate:
    point_id: int
    observation_key: str | None


@dataclass
class NextItem:
    item: BlindReviewItem
    round: int
    # 二次判读时给出前两次的判读（不含判读人）
    prior_labels: list[str] = field(default_factory=list)


def _rank(seed: int, purpose: str, point_id: int) -> str:
    return hashlib.sha256(f"{seed}|{purpose}|{point_id}".encode()).hexdigest()


def choose_items(candidates: Sequence[Candidate], spec: BatchSpec) -> list[tuple[int, str]]:
    """从候选照片里选出批次（纯函数）：固定参考株的全部照片 + 其余照片按种子随机抽 ``sample_size`` 张，再按种子打乱。

    返回按判读顺序排好的 (采样点编号, 来源)，来源是 reference 或 random。
    """
    keys = set(spec.reference_keys)
    reference = [c for c in candidates if c.observation_key in keys]
    rest = [c for c in candidates if c.observation_key not in keys]
    sample = sorted(rest, key=lambda c: (_rank(spec.seed, "sample", c.point_id), c.point_id))[: spec.sample_size]
    chosen = [(c.point_id, "reference") for c in reference] + [(c.point_id, "random") for c in sample]
    return sorted(chosen, key=lambda item: (_rank(spec.seed, "order", item[0]), item[0]))


def eligible(view: dict[str, Any] | None, side: str) -> bool:
    """补拍里不合格的那几次不收；只收叶背时，没有视角信息的点（协议 v1）也不收。"""
    view = view or {}
    if view.get("accepted") is False:
        return False
    return side == "any" or view.get("side") == "under"


def find_candidates(db: Session, spec: BatchSpec) -> list[Candidate]:
    rows = db.execute(
        select(CapturePoint.id, CapturePoint.observation_key, CapturePoint.captured_at, CapturePoint.view_meta)
        .join(Patrol, CapturePoint.patrol_id == Patrol.id)
        .where(Patrol.field_id == spec.field_id, CapturePoint.photo_url.is_not(None))
        .order_by(CapturePoint.id)
    )
    return [
        Candidate(point_id, key) for point_id, key, captured_at, view in rows
        if spec.date_from <= field_date(captured_at) <= spec.date_to and eligible(view, spec.side)
    ]


def create_batch(db: Session, spec: BatchSpec, *, name: str, created_by: str) -> BlindReviewBatch:
    chosen = choose_items(find_candidates(db, spec), spec)
    if not chosen:
        raise ValueError("这段日期里没有符合条件的照片（只收合格照片；只看叶背时还要有叶背视角信息）")
    if len(chosen) > MAX_ITEMS:
        raise ValueError(f"一批最多 {MAX_ITEMS} 张，当前 {len(chosen)} 张：缩小日期范围或减少固定参考株")
    batch = BlindReviewBatch(
        field_id=spec.field_id, name=name, seed=spec.seed, params=spec.params(),
        item_count=len(chosen), created_by=created_by, status="open",
    )
    batch.items = [
        BlindReviewItem(capture_point_id=point_id, position=index, origin=origin, status="pending")
        for index, (point_id, origin) in enumerate(chosen, start=1)
    ]
    db.add(batch)
    db.flush()
    return batch


def next_item(batch: BlindReviewBatch, user_id: int) -> NextItem | None:
    """给这位判读人的下一张：先做第 1 轮还缺人判读的，再做轮到别人分歧的二次判读；自己判过的不再给。"""
    if batch.status != "open":
        return None
    for item in batch.items:
        voters = {vote.reviewer_user_id for vote in item.votes}
        if item.status in ("pending", "partial") and user_id not in voters:
            return NextItem(item, 1)
    for item in batch.items:
        voters = {vote.reviewer_user_id for vote in item.votes}
        if item.status == "disputed" and user_id not in voters:
            return NextItem(item, 2, [vote.label for vote in item.votes if vote.round == 1])
    return None


def _resolve(db: Session, item: BlindReviewItem, label: str, now: datetime) -> None:
    """定论：写成该照片的标注（同标签已有则复用，不改原记录），批次记下标注编号。"""
    item.final_label = label
    item.resolved_at = now
    point = item.capture_point
    annotation = db.scalar(select(Annotation).where(
        Annotation.capture_point_id == point.id, Annotation.label == label,
    ))
    if annotation is None:
        names = "、".join(vote.reviewer_name for vote in item.votes)
        annotation = Annotation(
            capture_point_id=point.id, patrol_id=point.patrol_id, label=label,
            annotator_name=f"盲评：{names}"[:80], note=f"盲法复核批次 #{item.batch_id} 第 {item.position} 张",
        )
        db.add(annotation)
        db.flush()
    item.annotation_id = annotation.id


def cast_vote(
    db: Session,
    batch: BlindReviewBatch,
    item: BlindReviewItem,
    *,
    user_id: int,
    reviewer_name: str,
    label: str,
    now: datetime | None = None,
) -> BlindReviewItem:
    """记一次判读并推进状态：pending → partial → agreed / disputed → adjudicated（单人判读时第一票即定）。"""
    now = now or datetime.now(timezone.utc)
    if label not in BLIND_LABELS:
        raise ValueError(f"判读只能是 {'、'.join(BLIND_LABELS)} 之一")
    if batch.status != "open":
        raise ReviewConflict("这批已全部定论")
    if item.status in RESOLVED:
        raise ReviewConflict("这张已有定论")
    if any(vote.reviewer_user_id == user_id for vote in item.votes):
        raise ReviewConflict("你已经判读过这张")
    round_ = 2 if item.status == "disputed" else 1
    item.votes.append(BlindReviewVote(reviewer_user_id=user_id, reviewer_name=reviewer_name, label=label, round=round_))
    first_round = [vote.label for vote in item.votes if vote.round == 1]
    if round_ == 2:
        item.status = "adjudicated"
        _resolve(db, item, label, now)
    elif not batch.params.get("double_review", True):
        item.status = "agreed"
        _resolve(db, item, label, now)
    elif len(first_round) == 1:
        item.status = "partial"
    elif first_round[0] == first_round[1]:
        item.status = "agreed"
        _resolve(db, item, label, now)
    else:
        item.status = "disputed"
    if all(other.status in RESOLVED for other in batch.items):
        batch.status = "done"
        batch.done_at = now
    db.flush()
    return item


def cohen_kappa(pairs: Iterable[tuple[str, str]]) -> float | None:
    """两位判读人（按先后）的 Cohen's κ；没有成对判读时为空，期望一致率为 1 时只在完全一致时记 1。"""
    pairs = list(pairs)
    if not pairs:
        return None
    n = len(pairs)
    observed = sum(a == b for a, b in pairs) / n
    first, second = Counter(a for a, _ in pairs), Counter(b for _, b in pairs)
    expected = sum(first[k] * second[k] for k in set(first) | set(second)) / (n * n)
    if expected == 1:
        return 1.0 if observed == 1 else None
    return round((observed - expected) / (1 - expected), 4)


def summarize(batch: BlindReviewBatch, user_id: int | None = None) -> dict[str, Any]:
    """批次汇总：各状态张数、两人一致率与 κ、随机 / 参考两类的定论分布；不含单张判读。"""
    counts = Counter(item.status for item in batch.items)
    pairs = []
    for item in batch.items:
        first_round = [vote.label for vote in item.votes if vote.round == 1]
        if len(first_round) == 2:
            pairs.append((first_round[0], first_round[1]))
    by_origin: dict[str, Counter] = {"random": Counter(), "reference": Counter()}
    for item in batch.items:
        if item.final_label:
            by_origin.setdefault(item.origin, Counter())[item.final_label] += 1
    return {
        "status_counts": {status: counts.get(status, 0) for status in ("pending", "partial", "disputed", *RESOLVED)},
        "resolved": sum(counts.get(status, 0) for status in RESOLVED),
        "pairs": len(pairs),
        "agreement": round(sum(a == b for a, b in pairs) / len(pairs), 4) if pairs else None,
        "kappa": cohen_kappa(pairs),
        "final_labels": {origin: dict(sorted(counter.items())) for origin, counter in by_origin.items()},
        "my_votes": (
            sum(1 for item in batch.items for vote in item.votes if vote.reviewer_user_id == user_id)
            if user_id is not None else None
        ),
    }
