"""计划 0015：风险驱动巡检计划 planner-v0（纯函数）。"""
from datetime import date, datetime, timedelta, timezone

import pytest

from app.services.patrol_planner import (
    DEFAULT_PARAMS,
    PlannerParams,
    UnitInput,
    build_plan,
    plan_seed,
    reshoot_budget,
)
from app.services.plant_state import PlantState

DAY = date(2026, 10, 5)
NOW = datetime(2026, 10, 5, 0, tzinfo=timezone.utc)
WINDOW = {"date": DAY, "start": "05:30", "end": "08:30", "night_wet_hours": 6}


def _state(state="healthy", source="model", score=0.1, *, under_ok=True, reviewed_hours=None):
    seen = NOW - timedelta(days=1)
    return PlantState(
        state=state, source=source, confidence=0.3 if source == "model" else 1.0, model_score=score,
        last_seen_at=seen, last_under_ok_at=seen, last_under_accepted=under_ok,
        reviewed_at=None if reviewed_hours is None else seen + timedelta(hours=reviewed_hours),
    )


def _unit(i, state=None, *, seen=1.0, under_ok=1.0, nbr=0.0):
    return UnitInput(unit_id=i, key=f"R01-P{i:03d}", state=state or _state(), days_since_seen=seen,
                     days_since_under_ok=under_ok, neighbor_max_score=nbr, row_no=1, position_no=i)


def _env(index, window=None):
    return {"index": {"env_index": index, "coverage": 1.0 if index is not None else 0.2}, "morning_window": window}


def _plan(units, env, params=DEFAULT_PARAMS, field_id=1):
    return build_plan(units, env, plan_date=DAY, seed=plan_seed(field_id, DAY), params=params)


def _keys(plan, name):
    return [item.key for item in plan["lists"][name]]


def _field(n=60):
    units = [_unit(i) for i in range(1, n + 1)]
    units[3] = _unit(4, _state("early", score=0.55))
    units[4] = _unit(5, _state("symptomatic", score=0.9))
    units[5] = _unit(6, _state("symptomatic", "human", 0.9))  # 人工确认为明显：不进确认
    units[6] = _unit(7, _state(score=0.35, under_ok=False))  # 上次叶背不合格
    units[7] = _unit(8, seen=9, under_ok=9)  # 全覆盖到期
    units[8] = _unit(9, seen=None, under_ok=None)  # 从没拍到
    for i in range(10, 20):  # 再来 10 株到期的：补拍预算装不下，余下的必须进全覆盖
        units[i - 1] = _unit(i, seen=8, under_ok=8)
    return units


def test_high_env_index_gives_longer_reshoot_list_and_morning_window():
    low = _plan(_field(), _env(0.0))
    high = _plan(_field(), _env(1.0, WINDOW))
    assert len(high["lists"]["reshoot"]) > len(low["lists"]["reshoot"])
    assert reshoot_budget(60, 0.0) == 6 and reshoot_budget(60, 1.0) == 15
    assert high["window"] == WINDOW and low["window"] is None
    assert all("morning_window" in item.rationale["triggers"] for item in high["lists"]["reshoot"])


def test_low_env_still_has_coverage_and_random_spot_checks():
    plan = _plan(_field(), _env(0.0))
    assert plan["lists"]["random"] and plan["lists"]["coverage"]
    assert len(plan["lists"]["random"]) == 3  # 60 株 × 5%


def test_missing_env_index_is_treated_as_middle_not_low():
    plan = _plan(_field(), _env(None))
    assert plan["env"]["env_missing"] is True and plan["env"]["env_used"] == 0.5
    assert plan["reshoot_budget"] == reshoot_budget(60, 0.5) > reshoot_budget(60, 0.0)
    assert plan["lists"]["reshoot"][0].rationale["inputs"]["env_missing"] is True


def test_each_unit_appears_in_at_most_one_list():
    plan = _plan(_field(), _env(0.8, WINDOW))
    seen = [item.unit_id for name in plan["lists"] for item in plan["lists"][name]]
    assert len(seen) == len(set(seen))


def test_confirm_list_rules_and_human_budget():
    plan = _plan(_field(), _env(0.5))
    assert _keys(plan, "confirm") == ["R01-P005", "R01-P004"]  # 按模型分排序；人工确认明显的不推
    assert "R01-P006" not in _keys(plan, "reshoot")  # 也不占补拍预算
    params = PlannerParams(human_budget=1)
    plan = _plan(_field(), _env(0.5), params)
    assert _keys(plan, "confirm") == ["R01-P005"]
    # 超出人工预算的早期株照样参与补拍
    assert "R01-P004" in _keys(plan, "reshoot")


def test_human_reviewed_after_latest_photo_is_not_pushed_again():
    reviewed = _unit(1, _state("healthy", "human", 0.9, reviewed_hours=2))
    stale_review = _unit(2, _state("healthy", "human", 0.9, reviewed_hours=-2))  # 新照片在人工结论之后
    plan = _plan([reviewed, stale_review, *[_unit(i) for i in range(3, 20)]], _env(0.5))
    assert _keys(plan, "confirm") == ["R01-P002"]


def test_same_inputs_and_seed_give_identical_plan():
    first = _plan(_field(), _env(0.6, WINDOW))
    again = _plan(_field(), _env(0.6, WINDOW))
    assert first == again
    other_field = _plan(_field(), _env(0.6, WINDOW), field_id=2)
    assert _keys(other_field, "random") != _keys(first, "random") or len(first["lists"]["random"]) == 0


def test_coverage_due_units_are_always_selected():
    # 环境很低、补拍预算很小，到期株也必须入选（不是补拍就是全覆盖）
    due = {"R01-P008", "R01-P009", *(f"R01-P{i:03d}" for i in range(10, 20))}
    for index in (0.0, 1.0):
        plan = _plan(_field(), _env(index))
        assert due <= set(_keys(plan, "reshoot")) | set(_keys(plan, "coverage"))


def test_every_item_rationale_has_components():
    plan = _plan(_field(), _env(0.3, WINDOW))
    assert all(plan["lists"][name] for name in plan["lists"])
    for item in plan["lists"]["reshoot"]:
        r = item.rationale
        assert set(r["parts"]) == {"model", "neighbor", "env", "stale", "bad_quality"}
        assert r["score"] == pytest.approx(sum(r["parts"].values()))
        assert {"model_score", "neighbor_max_score", "env_index", "days_since_under_ok"} <= set(r["inputs"])
    for name in ("confirm", "coverage", "random"):
        for item in plan["lists"][name]:
            assert item.rationale["triggers"]
    bad = next(item for item in plan["lists"]["reshoot"] if item.key == "R01-P007")
    assert bad.rationale["parts"]["bad_quality"] == DEFAULT_PARAMS.bad_quality_bonus
    assert "last_under_rejected" in bad.rationale["triggers"]


def test_task_types_map_lists():
    plan = _plan(_field(), _env(0.3))
    types = {name: {item.task_type for item in plan["lists"][name]} for name in plan["lists"] if plan["lists"][name]}
    assert types == {"confirm": {"label"}, "reshoot": {"revisit"}, "coverage": {"coverage"}, "random": {"random"}}


def test_overrides_are_validated():
    assert DEFAULT_PARAMS.with_overrides({"human_budget": 2}).human_budget == 2
    for bad in ({"nope": 1}, {"human_budget": 1.5}, {"w_model": "x"}, {"reshoot_base_ratio": 0.5,
                                                                        "reshoot_high_ratio": 0.2}):
        with pytest.raises(ValueError):
            DEFAULT_PARAMS.with_overrides(bad)
