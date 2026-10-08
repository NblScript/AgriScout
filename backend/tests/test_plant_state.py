"""计划 0015：每株状态（纯函数）。"""
from datetime import datetime, timedelta, timezone

from app.services.plant_state import HumanLabel, Observation, PlantStateParams, plant_state

T0 = datetime(2026, 10, 1, 6, tzinfo=timezone.utc)


def _obs(hours, side="under", accepted=True, score=0.5):
    return Observation(T0 + timedelta(hours=hours), side, accepted, score, "placeholder-color-v0")


def test_no_observations_is_unknown():
    state = plant_state([], [])
    assert (state.state, state.source, state.confidence) == ("unknown", "none", 0.0)
    assert state.last_seen_at is None and state.model_score is None


def test_model_placeholder_uses_latest_accepted_under_photo_and_thresholds():
    observations = [
        _obs(0, score=0.9),
        _obs(1, side="upper", score=0.95),  # 正面不算
        _obs(2, accepted=False, score=0.99),  # 不合格不算
        _obs(3, score=0.5),
    ]
    state = plant_state(observations, [])
    assert (state.state, state.source, state.confidence, state.model_score) == ("early", "model", 0.3, 0.5)
    assert state.last_seen_at == T0 + timedelta(hours=3) and state.last_under_ok_at == T0 + timedelta(hours=3)
    assert state.last_under_accepted is True
    assert state.model_scored_at == T0 + timedelta(hours=3)
    # 最新的合格叶背图还没分析完：分数和它的拍摄时间都取上一张有分数的
    pending = plant_state([_obs(0, score=0.6), _obs(4, score=None)], [])
    assert (pending.model_score, pending.model_scored_at) == (0.6, T0)
    assert pending.last_under_ok_at == T0 + timedelta(hours=4)
    assert plant_state([_obs(0, score=0.7)], []).state == "symptomatic"
    assert plant_state([_obs(0, score=0.39)], []).state == "healthy"
    custom = PlantStateParams(early_threshold=0.2, symptomatic_threshold=0.3)
    assert plant_state([_obs(0, score=0.25)], [], custom).state == "early"


def test_observed_but_no_accepted_under_photo_is_unknown():
    state = plant_state([_obs(0, side="upper"), _obs(1, accepted=False)], [])
    assert (state.state, state.source) == ("unknown", "none")
    assert state.last_seen_at is not None and state.last_under_accepted is False


def test_latest_human_label_wins_over_model():
    labels = [
        HumanLabel("downy_mildew_early", T0 + timedelta(hours=5)),
        HumanLabel("normal", T0 + timedelta(hours=8)),
        HumanLabel("suspected_disease", T0 + timedelta(hours=9)),  # 小麦阶段的标签不改变状态
    ]
    state = plant_state([_obs(0, score=0.95)], labels)
    assert (state.state, state.source, state.confidence) == ("healthy", "human", 1.0)
    assert state.reviewed_at == T0 + timedelta(hours=8)
    assert state.model_score == 0.95  # 模型分照样给出，计划要用
    other = plant_state([], [HumanLabel("other", T0)])
    assert (other.state, other.source) == ("unknown", "human")
