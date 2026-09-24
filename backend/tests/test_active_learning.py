"""主动复巡/主动学习候选排序的纯函数测试。"""

import pytest

from app.services.active_learning import (
    ActiveLearningCandidate,
    SelectionConstraints,
    classify_task,
    rank_candidates,
    score_candidate,
    select_tasks,
)


def _candidate(candidate_id: str, **overrides) -> ActiveLearningCandidate:
    values = {
        "quality": 0.8,
        "uncertainty": 0.2,
        "risk": 0.2,
        "change": 0.2,
        "representativeness": 0.2,
        "cost": 0.2,
    }
    values.update(overrides)
    return ActiveLearningCandidate(candidate_id=candidate_id, **values)


def test_task_type_prefers_revisit_label_and_random_for_distinct_signals():
    low_quality = _candidate(
        "bad-image", quality=0.2, uncertainty=0.4, risk=0.7, change=0.7,
    )
    uncertain = _candidate(
        "uncertain", quality=0.9, uncertainty=0.9, risk=0.4,
    )
    representative = _candidate(
        "coverage", quality=0.9, uncertainty=0.1, risk=0.1,
        representativeness=0.95,
    )

    assert classify_task(low_quality) == "revisit"
    assert classify_task(uncertain) == "label"
    assert classify_task(representative) == "random"


def test_ranking_is_explainable_and_deterministic():
    candidates = [
        _candidate("z", quality=0.2, risk=0.8, change=0.8),
        _candidate("a", quality=0.9, uncertainty=0.85, risk=0.5),
        _candidate("m", quality=0.9, representativeness=0.9, risk=0.1),
    ]

    ranked = rank_candidates(candidates)
    reranked = rank_candidates(reversed(candidates))

    assert [row.candidate_id for row in ranked] == [row.candidate_id for row in reranked]
    assert [row.rank for row in ranked] == [1, 2, 3]
    for row in ranked:
        assert row.task_type in {"revisit", "label", "random"}
        assert 0 <= row.score <= 1
        assert set(row.task_scores) >= {row.task_type}
        assert row.signals["quality_gap"] == pytest.approx(1 - row.signals["quality"])
        assert row.reasons


def test_selection_applies_budget_quota_and_min_score_without_changing_scores():
    candidates = [
        _candidate("revisit", quality=0.1, risk=0.9, change=0.8, cost=0.6),
        _candidate("label", quality=0.9, uncertainty=0.95, risk=0.6, cost=0.4),
        _candidate("random", quality=0.9, representativeness=0.95, cost=0.2),
    ]
    constraints = SelectionConstraints(
        budget=0.6,
        max_tasks=2,
        max_label=1,
        min_score=0.4,
    )

    ranked = rank_candidates(candidates, constraints)
    selected = select_tasks(candidates, constraints)

    assert len(selected) <= 2
    assert sum(row.cost for row in selected) <= 0.6 + 1e-9
    assert sum(row.task_type == "label" for row in selected) <= 1
    assert all(row.score >= 0.4 for row in selected)
    assert all(
        next(item for item in ranked if item.candidate_id == row.candidate_id).score
        == row.score
        for row in selected
    )


def test_capability_and_allowed_type_constraints_fallback_or_skip():
    no_label = _candidate(
        "no-label", quality=0.95, uncertainty=0.95, labelable=False,
    )
    already_labeled = _candidate(
        "done", quality=0.95, uncertainty=0.95, already_labeled=True,
    )
    only_label_allowed = _candidate(
        "only-label", quality=0.2, uncertainty=0.2,
    )
    no_task = _candidate(
        "unavailable", revisitable=False, labelable=False, randomizable=False,
    )

    assert classify_task(no_label) == "random"
    assert classify_task(already_labeled) == "random"
    assert classify_task(
        only_label_allowed,
        SelectionConstraints(allowed_task_types=frozenset({"label"})),
    ) == "label"
    assert classify_task(no_task) is None
    assert [row.candidate_id for row in rank_candidates([no_task])] == []


def test_signal_clamping_and_input_validation():
    candidate = _candidate(
        "clamped", quality=2, uncertainty=-1, risk=0.5,
        change=0.5, representativeness=0.5, cost=0,
    )
    assert score_candidate(candidate, "label") == pytest.approx(0.4)
    with pytest.raises(ValueError, match="candidate_id"):
        ActiveLearningCandidate("", 0.5, 0.5, 0.5, 0.5, 0.5, 0.1)
    with pytest.raises(ValueError, match="cost"):
        _candidate("negative-cost", cost=-0.1)
    with pytest.raises(ValueError, match="重复"):
        rank_candidates([_candidate("same"), _candidate("same")])


def test_score_rejects_unknown_task_type():
    with pytest.raises(ValueError, match="未知任务类型"):
        score_candidate(_candidate("x"), "other")  # type: ignore[arg-type]
